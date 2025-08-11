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

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"


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
    """팀 총 인원(리더 제외)을 최대한 균등하게 맞추면서,
    여리더 팀에는 남성 그룹(ob,yb) 우선, 남리더 팀에는 여성 그룹(girls) 우선을 반영한다."""
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

    # 우선순위 순회 리스트 구성
    order_for_male_groups = female_leader_idx + others_from_female  # ob/yb는 여리더 우선
    order_for_girls = male_leader_idx + others_from_male            # girls는 남리더 우선

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
                # 모든 팀 capacity가 0이면 더 이상 배정 불가
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


st.set_page_config(page_title="워크샵 조 추첨기 (웹)", layout="wide")
st.title("워크샵 조 추첨기")

col_seed, col_btns = st.columns([1, 3])
with col_seed:
    seed_str = st.text_input("Seed (선택)", value="")
with col_btns:
    st.caption("CSV는 UTF-8 인코딩 권장. 헤더: leaders=name,gender / ob,yb,girls=name")

leaders_bytes = read_default_or_upload("Leaders", DATA_DIR / "leaders.csv")
ob_bytes = read_default_or_upload("OB", DATA_DIR / "ob.csv")
yb_bytes = read_default_or_upload("YB", DATA_DIR / "yb.csv")
girls_bytes = read_default_or_upload("Girls", DATA_DIR / "girls.csv")

if st.button("추첨 시작", type="primary"):
    try:
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

        # 간단한 애니메이션
        placeholder = st.empty()
        with placeholder.container():
            st.subheader("추첨 중...")
            for _ in range(12):
                st.progress(_ / 12)
                time.sleep(0.05)
        placeholder.empty()

        # 결과 표시 (2행 그리드로 정렬 보장)
        st.success("추첨 완료!")
        for row_start in (0, 4):
            cols = st.columns(4)
            for j in range(4):
                team = teams[row_start + j]
                with cols[j]:
                    st.markdown(f"**Team {team.index + 1}**")
                    st.write(f"Leader: {team.leader.name} ({team.leader.gender})")
                    for m in team.members:
                        st.write(f"- {m.name} [{m.group}]")

        # 엑셀 다운로드
        xlsx_bytes = export_to_excel_bytes(teams)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            label="엑셀 다운로드",
            data=xlsx_bytes,
            file_name=f"draw_result_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        st.error(str(e))
else:
    st.info("CSV를 업로드하거나 기본 파일을 사용한 후, '추첨 시작'을 눌러주세요.")
