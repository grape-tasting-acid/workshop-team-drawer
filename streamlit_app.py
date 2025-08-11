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
st.set_page_config(page_title="워크샵 조 추첨기", layout="wide")

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"

GROUP_COLORS = {"ob": "#1f77b4", "yb": "#2ca02c", "girls": "#d62728"}


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
) -> Dict[int, Dict[str, int]]:
    num_teams = len(leaders)
    total = ob_count + yb_count + girls_count
    base = total // num_teams
    remainder = total % num_teams

    remaining_capacity = [base + (1 if i < remainder else 0) for i in range(num_teams)]
    targets: Dict[int, Dict[str, int]] = {i: {"ob": 0, "yb": 0, "girls": 0} for i in range(num_teams)}

    male_leader_idx = [i for i, ld in enumerate(leaders) if ld.gender == "M"]
    female_leader_idx = [i for i, ld in enumerate(leaders) if ld.gender == "F"]
    others_from_female = [i for i in range(num_teams) if i not in female_leader_idx]
    others_from_male = [i for i in range(num_teams) if i not in male_leader_idx]

    order_for_male_groups = female_leader_idx + others_from_female
    order_for_girls = male_leader_idx + others_from_male

    def allocate(count: int, order: List[int], key: str) -> None:
        if count <= 0:
            return
        idx_pointer = 0
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

    allocate(ob_count, order_for_male_groups, "ob")
    allocate(yb_count, order_for_male_groups, "yb")
    allocate(girls_count, order_for_girls, "girls")

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
        leaders, ob_count=len(ob_list), yb_count=len(yb_list), girls_count=len(girls_list)
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

    return teams


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
    .team-card{background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:12px 14px;margin-bottom:10px}
    .team-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
    .team-title{font-weight:700;font-size:18px}
    .leader-chip{background:#eef2ff;border:1px solid #c7d2fe;color:#1f2937;border-radius:8px;padding:6px 8px;margin-bottom:8px;display:inline-block}
    .member-list{display:flex;flex-direction:column;gap:6px}
    .member-item{display:flex;align-items:center;gap:8px}
    .count-chip{background:#fff;border:1px solid #e5e7eb;border-radius:999px;padding:3px 10px;font-size:12px;margin-left:6px;color:#111}
    .badge{padding:2px 8px;border-radius:999px;color:#fff;font-size:12px}
    .badge-ob{background:#1f77b4}.badge-yb{background:#2ca02c}.badge-girls{background:#d62728}
    </style>
    """,
    unsafe_allow_html=True,
)

def group_badge(group: str) -> str:
    cls = f"badge badge-{group}"
    return f'<span class="{cls}">{group}</span>'

def member_item_html(mem: Member) -> str:
    return f'<div class="member-item"><span>{mem.name}</span> {group_badge(mem.group)}</div>'

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
        f'  <div class="leader-chip">👑 Leader: {leader.name}</div>'
        f'  <div class="member-list">{members_html}</div>'
        f'</div>'
    )


st.title("워크샵 조 추첨기")

col_seed, col_opts, col_hint = st.columns([1, 2, 3])
with col_seed:
    seed_str = st.text_input("Seed (선택)", value="")
with col_opts:
    dramatic = st.checkbox("드라마틱 모드", True)
    speed_ms = st.slider("애니메이션 속도(ms, 1인)", 80, 400, 150, 10)
    max_anim = st.slider("최대 애니메이션 인원", 16, 64, 40, 4)
with col_hint:
    st.caption("CSV는 UTF-8 인코딩 권장. 헤더: leaders=name,gender / ob,yb,girls=name")

status_ph = st.empty()

leaders_bytes = read_default_or_upload("Leaders", DATA_DIR / "leaders.csv")
ob_bytes = read_default_or_upload("OB", DATA_DIR / "ob.csv")
yb_bytes = read_default_or_upload("YB", DATA_DIR / "yb.csv")
girls_bytes = read_default_or_upload("Girls", DATA_DIR / "girls.csv")

if st.button("추첨 시작", type="primary"):
    try:
        status_ph.info("추첨 중...")
        leaders = read_leaders_csv_from_bytes(leaders_bytes)
        ob_list = read_names_csv_from_bytes(ob_bytes, group="ob", gender="M")
        yb_list = read_names_csv_from_bytes(yb_bytes, group="yb", gender="M")
        girls_list = read_names_csv_from_bytes(girls_bytes, group="girls", gender="F")

        # 리더와 일반 인원 중복 이름 제거
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

        seed_val: Optional[int] = int(seed_str) if seed_str.strip() else None
        teams = assign_members_to_teams(leaders, ob_list, yb_list, girls_list, seed=seed_val)

        # 결과 표시 (2행 그리드 + 드라마틱 모드)
        status_ph.success("추첨 완료!")

        # 팀 컨테이너 준비 (상단 텍스트 헤더 제거, 카드만 렌더)
        team_placeholders: List[st.delta_generator.DeltaGenerator] = []
        for row_start in (0, 4):
            cols = st.columns(4)
            for j in range(4):
                with cols[j]:
                    ph = st.empty()
                    team_placeholders.append(ph)

        # 라운드로빈 공개 순서 만들기
        max_len = max(len(t.members) for t in teams)
        reveal_queue: List[Tuple[int, Member]] = []
        for r in range(max_len):
            for i, t in enumerate(teams):
                if r < len(t.members):
                    reveal_queue.append((i, t.members[r]))

        # 팀별 누적 HTML
        team_lines: List[List[str]] = [[] for _ in range(8)]

        def render_team(i: int):
            html = build_team_card_html(teams[i].index, teams[i].leader, [m for m in teams[i].members if f"• {m.name}" in "\n".join(team_lines[i])])
            team_placeholders[i].markdown(html, unsafe_allow_html=True)

        # 드라마틱 모드: 일부만 애니메이션, 나머지는 즉시 렌더
        remaining_names = [m.name for _, m in reveal_queue]
        for idx, (ti, mem) in enumerate(reveal_queue):
            if dramatic and idx < max_anim:
                roll = st.empty()
                for _ in range(6):
                    sample = random.choice(remaining_names) if remaining_names else mem.name
                    roll.markdown(f"🎲 {sample}")
                    time.sleep(max(0.02, speed_ms / 1000 / 6))
                roll.empty()
            # 확정 출력(내부 상태에 추가)
            team_lines[ti].append(f"• {mem.name}")
            render_team(ti)
            if dramatic and idx < max_anim:
                time.sleep(max(0.01, speed_ms / 1000 * 0.35))
            try:
                remaining_names.remove(mem.name)
            except ValueError:
                pass

        # 요약 통계
        st.divider()
        cols_stat = st.columns(4)
        for i, col in enumerate(cols_stat):
            t = teams[i]
            with col:
                st.caption(
                    f"Team {t.index + 1}: 총 {1 + len(t.members)}명 (OB:{sum(1 for m in t.members if m.group=='ob')}, YB:{sum(1 for m in t.members if m.group=='yb')}, Girls:{sum(1 for m in t.members if m.group=='girls')})"
                )
        cols_stat2 = st.columns(4)
        for i, col in enumerate(cols_stat2):
            t = teams[4 + i]
            with col:
                st.caption(
                    f"Team {t.index + 1}: 총 {1 + len(t.members)}명 (OB:{sum(1 for m in t.members if m.group=='ob')}, YB:{sum(1 for m in t.members if m.group=='yb')}, Girls:{sum(1 for m in t.members if m.group=='girls')})"
                )

        # 엑셀 다운로드
        xlsx_bytes = export_to_excel_bytes(teams)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            label="엑셀 다운로드",
            data=xlsx_bytes,
            file_name=f"draw_result_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.balloons()

    except Exception as e:
        status_ph.empty()
        st.error(str(e))
else:
    status_ph.empty()
    st.info("CSV를 업로드하거나 기본 파일을 사용한 후, '추첨 시작'을 눌러주세요.")
