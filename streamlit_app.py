import csv
import io
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st
from openpyxl import Workbook
st.set_page_config(page_title="조 추첨기", layout="wide")

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"

GROUP_COLORS = {"ob": "#1f77b4", "yb": "#2ca02c", "girls": "#d62728"}

# 재밌는 멘트
QUIPS = [
    "이 분이 팀의 분위기 메이커?!",
    "오늘의 럭키가이(걸)!",
    "리더가 살짝 긴장하는 표정입니다...",
    "운명은 이미 정해져 있었다...",
    "오오오~~ 예상 밖의 조합!",
    "팀워크 시너지가 느껴진다!",
    "커피 쿠폰 걸고 달려봅시다 ☕️",
    "박수 갈까요? 👏",
    "환호 부탁드립니다! 🙌",
]


def toast(msg: str) -> None:
    try:
        st.toast(msg)
    except Exception:
        st.caption(msg)


@dataclass
class Member:
    name: str
    group: str  # one of {"leader", "ob", "yb", "girls"}
    gender: str  # one of {"M", "F"}


@dataclass
class Team:
    index: int
    leader: Member
    members: List[Member] = field(default_factory=list)

    def add_member(self, member: Member) -> None:
        self.members.append(member)

    def all_people(self) -> List[Member]:
        return [self.leader] + self.members


@dataclass
class Room:
    index: int
    members: List[Member] = field(default_factory=list)


def read_leaders_csv_from_bytes(data: bytes) -> List[Member]:
    leaders: List[Member] = []
    f = io.StringIO(data.decode("utf-8"))
    reader = csv.DictReader(f)
    for row in reader:
        name = (row.get("name") or row.get("Name") or "").strip()
        gender = (row.get("gender") or row.get("Gender") or "").strip().upper()
        if not name:
            continue
        if gender not in {"M", "F"}:
            raise ValueError(f"리더 성별은 M/F 로 표기해야 합니다: {name} -> {gender}")
        leaders.append(Member(name=name, group="leader", gender=gender))
    return leaders


def read_names_csv_from_bytes(data: bytes, group: str, gender: str) -> List[Member]:
    members: List[Member] = []
    f = io.StringIO(data.decode("utf-8"))
    reader = csv.DictReader(f)
    for row in reader:
        name = (row.get("name") or row.get("Name") or "").strip()
        if not name:
            continue
        members.append(Member(name=name, group=group, gender=gender))
    return members


def read_csv_from_disk(path: Path) -> bytes:
    if not path.exists():
        return b""
    return path.read_bytes()


def compute_balanced_targets(
    leaders: List[Member],
    ob_count: int,
    yb_count: int,
    girls_count: int,
    rng: random.Random,
) -> Dict[int, Dict[str, int]]:
    """팀 총 인원(리더 제외)을 최대한 균등하게 맞추되,
    - girls(여자) 인원은 팀별로 균등하게 분배하고, 여유분은 남리더 팀에 우선 배정한다.
    - 이후 남성 그룹(ob/yb)을 남리더 우선 순서로 나눠 남은 자리를 채운다.
    """
    num_teams = len(leaders)
    total = ob_count + yb_count + girls_count

    base = total // num_teams
    remainder = total % num_teams

    # 여분 1명을 받는 팀을 무작위로 선정
    extra_indices = rng.sample(range(num_teams), remainder) if remainder > 0 else []
    remaining_capacity = [base + (1 if i in extra_indices else 0) for i in range(num_teams)]

    targets: Dict[int, Dict[str, int]] = {i: {"ob": 0, "yb": 0, "girls": 0} for i in range(num_teams)}

    male_leader_idx = [i for i, ld in enumerate(leaders) if ld.gender == "M"]
    female_leader_idx = [i for i, ld in enumerate(leaders) if ld.gender == "F"]

    # 우선순위 리스트도 무작위 셔플
    rng.shuffle(male_leader_idx)
    rng.shuffle(female_leader_idx)
    others_from_female = [i for i in range(num_teams) if i not in female_leader_idx]
    others_from_male = [i for i in range(num_teams) if i not in male_leader_idx]
    rng.shuffle(others_from_female)
    rng.shuffle(others_from_male)

    order_for_male_groups = female_leader_idx + others_from_female  # ob/yb는 여리더 우선
    order_for_girls = male_leader_idx + others_from_male            # girls는 남리더 우선

    # 1) girls를 먼저 팀별로 균등 분배하되, 여유분은 남리더 우선
    if girls_count > 0:
        base_g = girls_count // num_teams
        rem_g = girls_count % num_teams
        girls_targets = [base_g for _ in range(num_teams)]
        # 여유분을 남리더 우선 순서대로 배정하되, 해당 팀에 남은 총 수용량이 base_g보다 커야 배정
        # (총 인원 여유가 없는 팀에 억지로 배정하지 않음)
        for team_i in order_for_girls:
            if rem_g <= 0:
                break
            if remaining_capacity[team_i] > girls_targets[team_i]:
                girls_targets[team_i] += 1
                rem_g -= 1
        # 혹시 rem_g가 남으면(모든 팀이 여유없었던 경우), 아무 팀이나 수용 가능 팀에 배정
        if rem_g > 0:
            for team_i in range(num_teams):
                if rem_g == 0:
                    break
                if remaining_capacity[team_i] > girls_targets[team_i]:
                    girls_targets[team_i] += 1
                    rem_g -= 1

        # capacity 차감 및 타겟 반영
        for i in range(num_teams):
            allocate_g = min(girls_targets[i], remaining_capacity[i])
            targets[i]["girls"] = allocate_g
            remaining_capacity[i] -= allocate_g

    def allocate(count: int, order: List[int], key: str) -> None:
        if count <= 0:
            return
        if not order:
            return
        # 시작 지점을 임의로 선택해 편향을 줄임
        idx_pointer = rng.randrange(len(order))
        while count > 0:
            progressed = False
            for j in range(len(order)):
                team_i = order[(idx_pointer + j) % len(order)]
                if remaining_capacity[team_i] > 0:
                    targets[team_i][key] += 1
                    remaining_capacity[team_i] -= 1
                    count -= 1
                    progressed = True
                    idx_pointer = (idx_pointer + j + 1) % len(order)
                    if count == 0:
                        break
            if not progressed:
                break

    # 2) 남은 좌석에 ob/yb 배정(남리더 우선 순서)
    allocate(ob_count, order_for_male_groups, "ob")
    allocate(yb_count, order_for_male_groups, "yb")

    return targets


def assign_members_to_teams(
    leaders: List[Member],
    ob_list: List[Member],
    yb_list: List[Member],
    girls_list: List[Member],
    seed: Optional[int] = None,
) -> List[Team]:
    if seed is None:
        seed = int(time.time() * 1000) % (2**32 - 1)
    rng = random.Random(seed)

    num_teams = len(leaders)
    if num_teams != 8:
        raise ValueError("리더 수는 반드시 8명이어야 합니다.")
    male_count = sum(1 for m in leaders if m.gender == "M")
    female_count = sum(1 for m in leaders if m.gender == "F")
    if male_count != 4 or female_count != 4:
        raise ValueError("리더 성별은 남 4, 여 4 이어야 합니다.")

    targets = compute_balanced_targets(
        leaders, ob_count=len(ob_list), yb_count=len(yb_list), girls_count=len(girls_list), rng=rng
    )

    rng.shuffle(ob_list)
    rng.shuffle(yb_list)
    rng.shuffle(girls_list)

    teams = [Team(index=i, leader=leaders[i]) for i in range(num_teams)]

    def pop_many(src: List[Member], count: int) -> List[Member]:
        if count <= 0:
            return []
        if count > len(src):
            raise ValueError("분배 대상 인원이 부족합니다. 입력 CSV를 확인하세요.")
        result = src[:count]
        del src[:count]
        return result

    for i in range(num_teams):
        teams[i].members.extend(pop_many(ob_list, targets[i]["ob"]))
    for i in range(num_teams):
        teams[i].members.extend(pop_many(yb_list, targets[i]["yb"]))
    for i in range(num_teams):
        teams[i].members.extend(pop_many(girls_list, targets[i]["girls"]))

    for team in teams:
        rng.shuffle(team.members)

    # 특별 룰: 특정 두 사람은 같은 팀이 되지 않도록 스왑으로 조정
    enforce_exclusion_pairs(teams, pairs=[("노시현", "배연경")])
    enforce_exclusion_pairs(teams, pairs=[("노시현", "이진원")])

    return teams


def enforce_exclusion_pairs(teams: List[Team], pairs: List[Tuple[str, str]]) -> None:
    name_to_location: Dict[str, Tuple[int, bool, int]] = {}

    def locate(name: str) -> Optional[Tuple[int, bool, int]]:
        for i, t in enumerate(teams):
            if t.leader.name == name:
                return (i, True, -1)
            for idx, m in enumerate(t.members):
                if m.name == name:
                    return (i, False, idx)
        return None

    def team_has_name(team: Team, name: str) -> bool:
        if team.leader.name == name:
            return True
        return any(m.name == name for m in team.members)

    def try_resolve_pair(a: str, b: str) -> None:
        loc_a = locate(a)
        loc_b = locate(b)
        if not loc_a or not loc_b:
            return
        team_a, a_is_leader, a_idx = loc_a
        team_b, b_is_leader, b_idx = loc_b
        if team_a != team_b:
            return  # already satisfied

        conflicted_team = team_a
        # 우선 멤버 쪽을 이동(리더는 그대로 두는 것을 우선)
        # 후보 1: a가 멤버이면 a를 이동 시도
        if not a_is_leader:
            src_member = teams[conflicted_team].members[a_idx]
            # 같은 그룹 멤버와 스왑하여 팀별 그룹 수를 유지
            for j, t in enumerate(teams):
                if j == conflicted_team:
                    continue
                if team_has_name(t, b):
                    continue  # b가 있는 팀으로 보내지 않음
                for j_idx, other in enumerate(t.members):
                    if other.group == src_member.group:
                        teams[conflicted_team].members[a_idx], t.members[j_idx] = t.members[j_idx], teams[conflicted_team].members[a_idx]
                        return
        # 후보 2: b가 멤버이면 b를 이동 시도
        if not b_is_leader:
            src_member = teams[conflicted_team].members[b_idx]
            for j, t in enumerate(teams):
                if j == conflicted_team:
                    continue
                if team_has_name(t, a):
                    continue
                for j_idx, other in enumerate(t.members):
                    if other.group == src_member.group:
                        teams[conflicted_team].members[b_idx], t.members[j_idx] = t.members[j_idx], teams[conflicted_team].members[b_idx]
                        return
        # 그래도 불가하면 마지막 수단: 같은 그룹이 아니더라도 멤버와 스왑(팀 총원만 유지)
        if not a_is_leader:
            for j, t in enumerate(teams):
                if j == conflicted_team:
                    continue
                if team_has_name(t, b):
                    continue
                if t.members:
                    teams[conflicted_team].members[a_idx], t.members[0] = t.members[0], teams[conflicted_team].members[a_idx]
                    return
        if not b_is_leader:
            for j, t in enumerate(teams):
                if j == conflicted_team:
                    continue
                if team_has_name(t, a):
                    continue
                if t.members:
                    teams[conflicted_team].members[b_idx], t.members[0] = t.members[0], teams[conflicted_team].members[b_idx]
                    return

    for a, b in pairs:
        try_resolve_pair(a, b)


def export_to_excel_bytes(teams: List[Team]) -> bytes:
    wb = Workbook()
    ws_by_team = wb.active
    ws_by_team.title = "ByTeam"
    ws_flat = wb.create_sheet("Flat")

    col = 1
    for team in teams:
        ws_by_team.cell(row=1, column=col, value=f"Team {team.index + 1}")
        ws_by_team.cell(row=2, column=col, value=f"Leader: {team.leader.name} ({team.leader.gender})")
        ws_by_team.cell(row=2, column=col + 1, value="leader")
        row = 3
        for m in team.members:
            ws_by_team.cell(row=row, column=col, value=m.name)
            ws_by_team.cell(row=row, column=col + 1, value=m.group)
            row += 1
        col += 3

    ws_flat.append(["team", "role", "group", "name", "gender"])
    for team in teams:
        ws_flat.append([team.index + 1, "leader", "leader", team.leader.name, team.leader.gender])
        for m in team.members:
            ws_flat.append([team.index + 1, "member", m.group, m.name, m.gender])

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.read()


def export_rooms_to_excel_bytes(male_rooms: List["Room"], female_rooms: List["Room"]) -> bytes:
    wb = Workbook()
    ws_m = wb.active
    ws_m.title = "Rooms_M"
    ws_f = wb.create_sheet("Rooms_F")
    ws_flat = wb.create_sheet("FlatRooms")

    # Rooms_M
    ws_m.append(["room", "name", "group", "gender"])
    for r in male_rooms:
        for mem in r.members:
            ws_m.append([r.index + 1, mem.name, mem.group, mem.gender])

    # Rooms_F
    ws_f.append(["room", "name", "group", "gender"])
    for r in female_rooms:
        for mem in r.members:
            ws_f.append([r.index + 1, mem.name, mem.group, mem.gender])

    # FlatRooms
    ws_flat.append(["gender_block", "room", "name", "group", "gender"])
    for r in male_rooms:
        for mem in r.members:
            ws_flat.append(["M", r.index + 1, mem.name, mem.group, mem.gender])
    for r in female_rooms:
        for mem in r.members:
            ws_flat.append(["F", r.index + 1, mem.name, mem.group, mem.gender])

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.read()


def read_default_or_upload(label: str, default_path: Path) -> bytes:
    uploaded = st.file_uploader(f"{label} CSV 업로드", type=["csv"], key=label)
    if uploaded is not None:
        return uploaded.read()
    with st.expander(f"{label} - 기본 파일 사용 경로 보기", expanded=False):
        st.code(str(default_path))
    return read_csv_from_disk(default_path)


def badge_html(group: str) -> str:
    color = GROUP_COLORS.get(group, "#666")
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:12px;font-size:12px">{group}</span>'

# 전역 스타일(CSS)
st.markdown(
    """
    <style>
    .team-card{background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:12px 14px;margin-bottom:10px;transition:border-color .2s, box-shadow .2s}
    .team-card.highlight{border-color:#f59e0b;box-shadow:0 0 0 3px rgba(245,158,11,.25);animation:glow .8s ease-in-out 2 alternate}
    .team-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
    .team-title{font-weight:700;font-size:18px}
    .leader-chip{background:transparent;border:none;color:#0f172a;border-radius:0;padding:0;margin:4px 0 8px;display:flex;align-items:center;gap:8px}
    .leader-crown{display:inline-flex;align-items:center;justify-content:center;font-size:18px;line-height:1}
    .member-list{display:flex;flex-direction:column;gap:6px}
    .member-item{display:flex;align-items:center;gap:8px}
    .member-name{font-size:16px;font-weight:400;color:#0f172a}
    .leader-name{font-size:20px;font-weight:800;color:#0f172a}
    .leader-label{display:inline-flex;align-items:center;justify-content:center;width:64px;padding:2px 8px;margin:0;border-radius:999px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;background:#fde68a;border:1px solid #f59e0b;color:#78350f}
    .count-chip{background:#fff;border:1px solid #e5e7eb;border-radius:999px;padding:3px 10px;font-size:12px;margin-left:6px;color:#111}
    .badge{display:inline-flex;align-items:center;justify-content:center;width:64px;padding:2px 8px;border-radius:999px;color:#fff;font-size:12px}
    .badge-ob{background:#1f77b4}.badge-yb{background:#2ca02c}.badge-girls{background:#d62728}.badge-leader{background:#7c3aed}
    @keyframes glow{from{box-shadow:0 0 0 0 rgba(245,158,11,.0)}to{box-shadow:0 0 0 6px rgba(245,158,11,.15)}}
    .spotlight{background:linear-gradient(135deg,#f0f9ff,#e9d5ff);border:1px solid #e5e7eb;border-radius:14px;padding:16px 18px;margin:8px 0;text-align:center;box-shadow:0 8px 24px rgba(15,23,42,.06)}
    .spotlight .label{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
    .spotlight strong{font-size:32px;color:#0f172a}
    </style>
    """,
    unsafe_allow_html=True,
)

def group_badge(group: str) -> str:
    label = group.upper()
    cls = f"badge badge-{group}"
    return f'<span class="{cls}">{label}</span>'

def member_item_html(mem: Member) -> str:
    return f'<div class="member-item">{group_badge(mem.group)}<span class="member-name">{mem.name}</span></div>'

def build_team_card_html(team_idx: int, leader: Member, members: List[Member]) -> str:
    total = 1 + len(members)
    ob_c = sum(1 for m in members if m.group == "ob")
    yb_c = sum(1 for m in members if m.group == "yb")
    g_c = sum(1 for m in members if m.group == "girls")
    members_html = "\n".join(member_item_html(m) for m in members)
    header_counts = (
        f'<span class="count-chip">총 {total}명</span>'
        f'<span class="count-chip">OB {ob_c}</span>'
        f'<span class="count-chip">YB {yb_c}</span>'
        f'<span class="count-chip">Girls {g_c}</span>'
    )
    return (
        f'<div class="team-card">'
        f'  <div class="team-header">'
        f'    <div class="team-title">Team {team_idx + 1}</div>'
        f'    <div>{header_counts}</div>'
        f'  </div>'
        f'  <div class="leader-chip"><span class="leader-label">LEADER</span><span class="leader-name">{leader.name}</span><span class="leader-crown"> 👑</span></div>'
        f'  <div class="member-list">{members_html}</div>'
        f'</div>'
    )


def build_room_card_html(room_idx: int, members: List[Member], title_prefix: str = "Room") -> str:
    members_html = "\n".join(member_item_html(m) for m in members)
    return (
        f'<div class="team-card">'
        f'  <div class="team-header">'
        f'    <div class="team-title">{title_prefix} {room_idx + 1}</div>'
        f'  </div>'
        f'  <div class="member-list">{members_html}</div>'
        f'</div>'
    )


def assign_rooms(
    leaders: List[Member],
    ob_list: List[Member],
    yb_list: List[Member],
    girls_list: List[Member],
    room_size: int = 4,
    seed: Optional[int] = None,
) -> Tuple[List[Room], List[Room]]:
    if seed is None:
        seed = int(time.time() * 1000) % (2**32 - 1)
    rng = random.Random(seed)

    male_leaders = [m for m in leaders if m.gender == "M"]
    female_leaders = [m for m in leaders if m.gender == "F"]

    # 중복 제거: 리더 우선, 그 다음 기존 그룹
    def dedup_by_name(preferred: List[Member], others: List[Member]) -> List[Member]:
        name_to_member: Dict[str, Member] = {}
        for m in preferred:
            if m.name.strip():
                name_to_member.setdefault(m.name, m)
        for m in others:
            if m.name.strip() and m.name not in name_to_member:
                name_to_member[m.name] = m
        return list(name_to_member.values())

    male_pool = dedup_by_name(male_leaders, ob_list + yb_list)
    female_pool = dedup_by_name(female_leaders, girls_list)

    rng.shuffle(male_pool)
    rng.shuffle(female_pool)

    def build_room_sizes(total: int, preferred_size: int) -> List[int]:
        if total <= 0:
            return []
        if total < 3:
            return [total]
        k = total // preferred_size
        r = total % preferred_size
        sizes: List[int] = []
        if r == 0:
            sizes = [preferred_size] * k
        elif r == 3:
            sizes = [preferred_size] * k + [3]
        elif r == 2:
            if k >= 1:
                sizes = [preferred_size] * (k - 1) + [3, 3]
            else:
                sizes = [2]
        elif r == 1:
            if k >= 2:
                sizes = [preferred_size] * (k - 2) + [3, 3, 3]
            elif k == 1:
                sizes = [3, 2]
            else:
                sizes = [1]
        return sizes

    def compose_rooms(members: List[Member], preferred_size: int) -> List[Room]:
        sizes = build_room_sizes(len(members), preferred_size)
        rooms: List[Room] = []
        cursor = 0
        for sz in sizes:
            rooms.append(Room(index=len(rooms), members=members[cursor: cursor + sz]))
            cursor += sz
        return rooms

    return compose_rooms(male_pool, room_size), compose_rooms(female_pool, room_size)


st.title("조 추첨기")

# 세션 상태 초기화
for _k in [
    "leaders_bytes",
    "ob_bytes",
    "yb_bytes",
    "girls_bytes",
    "seed_str",
    "teams_result",
    "rooms_result_m",
    "rooms_result_f",
    "rooms_seed_str",
    "rooms_reveal_pending",
]:
    st.session_state.setdefault(_k, None)

tab_settings, tab_draw, tab_rooms = st.tabs(["설정", "조 추첨", "룸메이트"]) 

with tab_settings:
    st.subheader("설정")
    st.caption("CSV는 UTF-8 인코딩 권장. 헤더: leaders=name,gender / ob,yb,girls=name")
    st.session_state["seed_str"] = st.text_input(
        "Seed (선택)", value=st.session_state.get("seed_str") or ""
    )
    st.session_state["rooms_seed_str"] = st.text_input(
        "Room Seed (선택)", value=st.session_state.get("rooms_seed_str") or ""
    )
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.session_state["highlight_sec"] = st.slider(
            "하이라이트 시간(초)", min_value=0.0, max_value=1.0,
            value=float(st.session_state.get("highlight_sec") or 0.15), step=0.01
        )
    with col_t2:
        st.session_state["interval_sec"] = st.slider(
            "노출 텀(초)", min_value=0.0, max_value=1.0,
            value=float(st.session_state.get("interval_sec") or 0.24), step=0.01
        )
    st.divider()
    st.write("파일 업로드 또는 기본 파일 사용")
    leaders_bytes = read_default_or_upload("Leaders", DATA_DIR / "leaders.csv")
    ob_bytes = read_default_or_upload("OB", DATA_DIR / "ob.csv")
    yb_bytes = read_default_or_upload("YB", DATA_DIR / "yb.csv")
    girls_bytes = read_default_or_upload("Girls", DATA_DIR / "girls.csv")

    st.session_state["leaders_bytes"] = leaders_bytes
    st.session_state["ob_bytes"] = ob_bytes
    st.session_state["yb_bytes"] = yb_bytes
    st.session_state["girls_bytes"] = girls_bytes

    try:
        leaders_preview = read_leaders_csv_from_bytes(leaders_bytes) if leaders_bytes else []
        ob_preview = read_names_csv_from_bytes(ob_bytes, group="ob", gender="M") if ob_bytes else []
        yb_preview = read_names_csv_from_bytes(yb_bytes, group="yb", gender="M") if yb_bytes else []
        girls_preview = read_names_csv_from_bytes(girls_bytes, group="girls", gender="F") if girls_bytes else []
        st.info(
            f"리더 {len(leaders_preview)}명, OB {len(ob_preview)}명, YB {len(yb_preview)}명, Girls {len(girls_preview)}명"
        )
    except Exception as e:
        st.warning(str(e))

with tab_draw:
    st.subheader("조 추첨")
    status_ph = st.empty()
    if st.button("추첨 실행", type="primary"):
        try:
            status_ph.info("추첨 중…")
            leaders_bytes = st.session_state.get("leaders_bytes") or read_csv_from_disk(DATA_DIR / "leaders.csv")
            ob_bytes = st.session_state.get("ob_bytes") or read_csv_from_disk(DATA_DIR / "ob.csv")
            yb_bytes = st.session_state.get("yb_bytes") or read_csv_from_disk(DATA_DIR / "yb.csv")
            girls_bytes = st.session_state.get("girls_bytes") or read_csv_from_disk(DATA_DIR / "girls.csv")

            leaders = read_leaders_csv_from_bytes(leaders_bytes)
            ob_list = read_names_csv_from_bytes(ob_bytes, group="ob", gender="M")
            yb_list = read_names_csv_from_bytes(yb_bytes, group="yb", gender="M")
            girls_list = read_names_csv_from_bytes(girls_bytes, group="girls", gender="F")

            leader_names = {m.name for m in leaders}
            before_counts = (len(ob_list), len(yb_list), len(girls_list))
            ob_list = [m for m in ob_list if m.name not in leader_names]
            yb_list = [m for m in yb_list if m.name not in leader_names]
            girls_list = [m for m in girls_list if m.name not in leader_names]
            after_counts = (len(ob_list), len(yb_list), len(girls_list))
            if before_counts != after_counts:
                removed_ob = before_counts[0] - after_counts[0]
                removed_yb = before_counts[1] - after_counts[1]
                removed_girls = before_counts[2] - after_counts[2]
                st.info(
                    f"리더와 중복된 이름을 제외했습니다. 제거됨 - OB:{removed_ob}, YB:{removed_yb}, Girls:{removed_girls}"
                )

            seed_str = st.session_state.get("seed_str") or ""
            seed_val: Optional[int] = int(seed_str) if seed_str.strip() else None
            teams = assign_members_to_teams(leaders, ob_list, yb_list, girls_list, seed=seed_val)

            st.session_state["teams_result"] = teams
            st.session_state["reveal_pending"] = True
            status_ph.info("추첨 중…")
        except Exception as e:
            status_ph.empty()
            st.error(str(e))

    teams_draw = st.session_state.get("teams_result")
    if teams_draw:
        st.divider()
        # 전광판(상단)
        spotlight = st.empty()
        # 팀 카드 자리(리더만 먼저 표시)
        team_placeholders: List[st.delta_generator.DeltaGenerator] = []
        for row_start in (0, 4):
            cols = st.columns(4)
            for j in range(4):
                with cols[j]:
                    ph = st.empty()
                    team_placeholders.append(ph)
        for i in range(8):
            team_placeholders[i].markdown(
                build_team_card_html(teams_draw[i].index, teams_draw[i].leader, []),
                unsafe_allow_html=True,
            )

        # 전광판 + 순차 공개(사용자 설정 속도)
        highlight_sec = float(st.session_state.get("highlight_sec") or 0.15)
        interval_sec = float(st.session_state.get("interval_sec") or 0.24)
        if st.session_state.get("reveal_pending"):
            status_ph.info("추첨 진행 중…")
            revealed_by_team: List[List[Member]] = [[] for _ in range(8)]
            reveal_order: List[Tuple[int, Member]] = []
            for i, t in enumerate(teams_draw):
                for m in t.members:
                    reveal_order.append((i, m))
            seed_txt = (st.session_state.get("seed_str") or "").strip()
            try:
                seed_val_for_reveal = int(seed_txt) if seed_txt else None
            except Exception:
                seed_val_for_reveal = None
            rng = random.Random(seed_val_for_reveal if seed_val_for_reveal is not None else int(time.time()))
            rng.shuffle(reveal_order)

            for _, (ti, mem) in enumerate(reveal_order):
                spotlight.markdown(
                    f"<div class='spotlight'><div class='label'>Who's next?</div><strong>{mem.name}</strong></div>",
                    unsafe_allow_html=True,
                )
                revealed_by_team[ti].append(mem)
                # 하이라이트 효과로 짧게 반짝
                html_temp = build_team_card_html(teams_draw[ti].index, teams_draw[ti].leader, revealed_by_team[ti])
                html_temp = html_temp.replace("team-card", "team-card highlight", 1)
                team_placeholders[ti].markdown(html_temp, unsafe_allow_html=True)
                time.sleep(max(0.0, highlight_sec))
                team_placeholders[ti].markdown(
                    build_team_card_html(teams_draw[ti].index, teams_draw[ti].leader, revealed_by_team[ti]),
                    unsafe_allow_html=True,
                )
                # 전체 속도 조절(사용자 설정)
                time.sleep(max(0.0, interval_sec))
            spotlight.empty()
            status_ph.success("추첨 완료!")
            st.session_state["reveal_pending"] = False
        else:
            # 애니메이션 없이 전체 멤버 즉시 렌더
            for i in range(8):
                team_placeholders[i].markdown(
                    build_team_card_html(teams_draw[i].index, teams_draw[i].leader, teams_draw[i].members),
                    unsafe_allow_html=True,
                )
            status_ph.success("추첨 완료!")

        # 요약 통계
        st.divider()
        cols_stat = st.columns(4)
        for i, col in enumerate(cols_stat):
            t = teams_draw[i]
            with col:
                st.caption(
                    f"Team {t.index + 1}: 총 {1 + len(t.members)}명 (OB:{sum(1 for m in t.members if m.group=='ob')}, YB:{sum(1 for m in t.members if m.group=='yb')}, Girls:{sum(1 for m in t.members if m.group=='girls')})"
                )
        cols_stat2 = st.columns(4)
        for i, col in enumerate(cols_stat2):
            t = teams_draw[4 + i]
            with col:
                st.caption(
                    f"Team {t.index + 1}: 총 {1 + len(t.members)}명 (OB:{sum(1 for m in t.members if m.group=='ob')}, YB:{sum(1 for m in t.members if m.group=='yb')}, Girls:{sum(1 for m in t.members if m.group=='girls')})"
                )

        # 엑셀 다운로드
        xlsx_bytes = export_to_excel_bytes(teams_draw)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            label="엑셀 다운로드",
            data=xlsx_bytes,
            file_name=f"draw_result_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_button_draw",
        )
        st.balloons()


with tab_rooms:
    st.subheader("룸메이트 배정 (4인 1실, 성별 분리)")
    st.caption("리더 여부와 무관하게 성별을 기준으로 4인실로 배정합니다. 업로드한 CSV(리더/OB/YB/Girls)를 그대로 재사용합니다.")

    # 옵션: 방 크기(기본 4). 시드는 설정 탭(Room Seed) 사용
    room_size = st.number_input("방 정원", min_value=2, max_value=6, value=4, step=1)

    col_rooms_actions = st.columns(2)
    status_rooms = st.empty()
    with col_rooms_actions[0]:
        if st.button("룸메이트 배정 실행", type="primary"):
            try:
                leaders_bytes = st.session_state.get("leaders_bytes") or read_csv_from_disk(DATA_DIR / "leaders.csv")
                ob_bytes = st.session_state.get("ob_bytes") or read_csv_from_disk(DATA_DIR / "ob.csv")
                yb_bytes = st.session_state.get("yb_bytes") or read_csv_from_disk(DATA_DIR / "yb.csv")
                girls_bytes = st.session_state.get("girls_bytes") or read_csv_from_disk(DATA_DIR / "girls.csv")

                leaders_all = read_leaders_csv_from_bytes(leaders_bytes) if leaders_bytes else []
                ob_list = read_names_csv_from_bytes(ob_bytes, group="ob", gender="M") if ob_bytes else []
                yb_list = read_names_csv_from_bytes(yb_bytes, group="yb", gender="M") if yb_bytes else []
                girls_list = read_names_csv_from_bytes(girls_bytes, group="girls", gender="F") if girls_bytes else []

                # 시드 처리: 설정 탭의 Room Seed 사용
                seed_val_rooms: Optional[int] = None
                seed_text = (st.session_state.get("rooms_seed_str") or "").strip()
                if seed_text:
                    try:
                        seed_val_rooms = int(seed_text)
                    except Exception:
                        seed_val_rooms = None

                rooms_m, rooms_f = assign_rooms(
                    leaders=leaders_all,
                    ob_list=ob_list,
                    yb_list=yb_list,
                    girls_list=girls_list,
                    room_size=int(room_size),
                    seed=seed_val_rooms,
                )
                st.session_state["rooms_result_m"] = rooms_m
                st.session_state["rooms_result_f"] = rooms_f
                st.session_state["rooms_reveal_pending"] = True
                status_rooms.info("룸메이트 배정 중…")
            except Exception as e:
                status_rooms.error(str(e))

    rooms_m = st.session_state.get("rooms_result_m")
    rooms_f = st.session_state.get("rooms_result_f")

    if rooms_m or rooms_f:
        st.divider()
        spotlight_rooms = st.empty()

        # 남자 방 자리(빈 카드 먼저)
        male_room_placeholders: List[st.delta_generator.DeltaGenerator] = []
        if rooms_m:
            st.markdown("### 남자 방")
            cols_m = st.columns(4)
            for i, r in enumerate(rooms_m):
                with cols_m[i % 4]:
                    ph = st.empty()
                    male_room_placeholders.append(ph)
            for i, r in enumerate(rooms_m):
                male_room_placeholders[i].markdown(
                    build_room_card_html(r.index, [], title_prefix="Room(M)"),
                    unsafe_allow_html=True,
                )

        # 여자 방 자리(빈 카드 먼저)
        female_room_placeholders: List[st.delta_generator.DeltaGenerator] = []
        if rooms_f:
            st.markdown("### 여자 방")
            cols_f = st.columns(4)
            for i, r in enumerate(rooms_f):
                with cols_f[i % 4]:
                    ph = st.empty()
                    female_room_placeholders.append(ph)
            for i, r in enumerate(rooms_f):
                female_room_placeholders[i].markdown(
                    build_room_card_html(r.index, [], title_prefix="Room(F)"),
                    unsafe_allow_html=True,
                )

        highlight_sec = float(st.session_state.get("highlight_sec") or 0.15)
        interval_sec = float(st.session_state.get("interval_sec") or 0.24)

        if st.session_state.get("rooms_reveal_pending"):
            # 전개 순서(M/F 섞어서)
            reveal_order: List[Tuple[str, int, Member]] = []
            if rooms_m:
                for i, r in enumerate(rooms_m):
                    for m in r.members:
                        reveal_order.append(("M", i, m))
            if rooms_f:
                for i, r in enumerate(rooms_f):
                    for m in r.members:
                        reveal_order.append(("F", i, m))

            # 시드 기반 셔플(설정의 Room Seed)
            seed_text = (st.session_state.get("rooms_seed_str") or "").strip()
            try:
                seed_val_for_reveal = int(seed_text) if seed_text else None
            except Exception:
                seed_val_for_reveal = None
            rng = random.Random(seed_val_for_reveal if seed_val_for_reveal is not None else int(time.time()))
            rng.shuffle(reveal_order)

            revealed_m: List[List[Member]] = [[] for _ in range(len(rooms_m or []))]
            revealed_f: List[List[Member]] = [[] for _ in range(len(rooms_f or []))]

            for _, (gender_block, idx, mem) in enumerate(reveal_order):
                spotlight_rooms.markdown(
                    f"<div class='spotlight'><div class='label'>Who's next?</div><strong>{mem.name}</strong></div>",
                    unsafe_allow_html=True,
                )
                if gender_block == "M" and rooms_m:
                    revealed_m[idx].append(mem)
                    html_temp = build_room_card_html(rooms_m[idx].index, revealed_m[idx], title_prefix="Room(M)")
                    html_temp = html_temp.replace("team-card", "team-card highlight", 1)
                    male_room_placeholders[idx].markdown(html_temp, unsafe_allow_html=True)
                    time.sleep(max(0.0, highlight_sec))
                    male_room_placeholders[idx].markdown(
                        build_room_card_html(rooms_m[idx].index, revealed_m[idx], title_prefix="Room(M)"),
                        unsafe_allow_html=True,
                    )
                elif gender_block == "F" and rooms_f:
                    revealed_f[idx].append(mem)
                    html_temp = build_room_card_html(rooms_f[idx].index, revealed_f[idx], title_prefix="Room(F)")
                    html_temp = html_temp.replace("team-card", "team-card highlight", 1)
                    female_room_placeholders[idx].markdown(html_temp, unsafe_allow_html=True)
                    time.sleep(max(0.0, highlight_sec))
                    female_room_placeholders[idx].markdown(
                        build_room_card_html(rooms_f[idx].index, revealed_f[idx], title_prefix="Room(F)"),
                        unsafe_allow_html=True,
                    )
                time.sleep(max(0.0, interval_sec))

            spotlight_rooms.empty()
            status_rooms.success("룸메이트 배정 완료")
            st.session_state["rooms_reveal_pending"] = False
        else:
            # 애니메이션 없이 전체 렌더
            if rooms_m:
                for i, r in enumerate(rooms_m):
                    male_room_placeholders[i].markdown(
                        build_room_card_html(r.index, r.members, title_prefix="Room(M)"),
                        unsafe_allow_html=True,
                    )
            if rooms_f:
                for i, r in enumerate(rooms_f):
                    female_room_placeholders[i].markdown(
                        build_room_card_html(r.index, r.members, title_prefix="Room(F)"),
                        unsafe_allow_html=True,
                    )

        # 요약
        st.divider()
        if rooms_m:
            total_m = sum(len(r.members) for r in rooms_m)
            st.caption(f"남자: 방 {len(rooms_m)}개, 총 {total_m}명")
        if rooms_f:
            total_f = sum(len(r.members) for r in rooms_f)
            st.caption(f"여자: 방 {len(rooms_f)}개, 총 {total_f}명")

        # 엑셀 다운로드
        xlsx_rooms = export_rooms_to_excel_bytes(rooms_m or [], rooms_f or [])
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            label="룸메이트 엑셀 다운로드",
            data=xlsx_rooms,
            file_name=f"roommates_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_button_rooms",
        )
