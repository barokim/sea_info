from __future__ import annotations

import hashlib
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st

from sea_info import store
from sea_info.imaging import prepare_image
from sea_info.safe_ui import safe_bar_chart, safe_dataframe, safe_line_chart
from sea_info.scr06_post_detail import open_post_detail

SPECIES = [
    {"name": "흰동가리", "scientific": "Amphiprion ocellaris", "emoji": "🐠", "habitat": "따뜻한 열대 바다의 산호초 주변", "diet": "작은 갑각류와 플랑크톤", "summary": "말미잘과 공생하며 산호초 생태계에서 살아갑니다.", "confidence": .91},
    {"name": "불가사리", "scientific": "Asteroidea", "emoji": "⭐", "habitat": "바위 해안과 얕은 바다 바닥", "diet": "조개류와 작은 무척추동물", "summary": "관족을 이용해 움직이며 종에 따라 재생 능력이 있습니다.", "confidence": .84},
    {"name": "소라게", "scientific": "Paguroidea", "emoji": "🦀", "habitat": "조수 웅덩이와 바위 해안", "diet": "조류, 작은 동물, 유기물", "summary": "연약한 배를 보호하려고 빈 고둥 껍데기를 빌려 씁니다.", "confidence": .78},
]
QUIZ = [
    ("흰동가리는 주로 어디에서 살아갈까요?", ["사막", "말미잘 주변", "눈 덮인 산"], 1, "흰동가리는 산호초의 말미잘과 공생합니다."),
    ("불가사리는 어떤 무리에 속할까요?", ["극피동물", "포유류", "조류"], 0, "불가사리는 성게와 함께 극피동물에 속합니다."),
]


def identity() -> tuple[str, str]:
    role = st.session_state.get("role", "guest")
    email = st.session_state.get("email", "")
    return role, email or ("운영자" if role == "admin" else "바다탐험가" if role == "member" else "비회원")


def require_member() -> bool:
    if st.session_state.get("role", "guest") == "guest":
        st.info("이 기능은 로그인이 필요합니다.")
        st.page_link("pages/home.py", label="홈으로")
        st.page_link("pages/login.py", label="로그인 / 회원가입")
        return False
    return True


def header(screen_id: str, title: str, description: str) -> None:
    st.caption(f"{screen_id} · Sea-Info Agent")
    st.title(title)
    st.write(description)


def home() -> None:
    role, user = identity()
    header("SCR-01", "바다를 더 가까이", "관찰하고, 기록하고, 함께 배우는 해양생물 탐구 공간")
    main, aside = st.columns([2.3, 1])
    with main:
        with st.container(border=True):
            st.caption("DISCOVER THE OCEAN")
            st.header("이 생물, 이름이 뭘까요?")
            st.write("사진을 찍거나 앨범에서 골라 바다 생물을 알아보세요.")
            st.page_link("pages/explore.py", label="사진으로 생물 알아보기", icon="🔎")
        st.subheader("다른 사용자의 최근 생물 관찰")
        public_posts = [p for p in store.observations() if p["is_public"] and not p.get("is_hidden")]
        for post in public_posts[:3]:
            with st.container(border=True):
                a, b = st.columns([3, 1])
                a.markdown(f"**{post['title']}**")
                location = post["region"] if post["location_visibility"] != "비공개" else "위치 비공개"
                a.caption(f"{post['species']} · {post['author']} · {location}")
                b.metric("♡", post["likes"])
        if b.button("자세히", key=f"home_open_{post['id']}"):
            open_post_detail(post["id"], "pages/home.py", "홈", keep_keys=())
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            st.subheader("🐠 나의 수족관")
            st.write("관찰한 생물을 나만의 도감에 모아보세요.")
            st.page_link("pages/aquarium.py" if role != "guest" else "pages/login.py", label="수족관 둘러보기" if role != "guest" else "로그인 후 둘러보기")
        with c2, st.container(border=True):
            st.subheader("🌊 해양생물 퀴즈")
            st.write("퀴즈로 풀고 바다에 한 걸음 더 가까이.")
            st.page_link("pages/games.py", label="퀴즈 시작하기")
    with aside:
        with st.container(border=True):
            st.subheader("오늘의 물때")
            st.caption("예시 데이터 · 실제 관측값이 아닙니다")
            region = st.session_state.get("selected_region", "제주")
            st.write(f"관측 지역: **{region}**")
            with st.popover("지역 변경 · SCR-15"):
                query = st.text_input("지역 검색", key="tide_region_query")
                regions = [name for name in ["제주", "부산", "강릉", "인천", "속초", "여수"] if query.casefold() in name.casefold()]
                new_region = st.selectbox("지역 선택", regions or [region], key="tide_region_choice")
                if st.button("지역 적용"):
                    st.session_state.selected_region = new_region
                    st.toast(f"{new_region} 지역을 선택했습니다.")
                    st.rerun()
            x, y, z = st.columns(3)
            x.metric("만조", "06:24")
            y.metric("간조", "12:40")
            z.metric("파고", "0.8 m")
            st.page_link("pages/home.py", label="지역 변경 · SCR-15")
        with st.container(border=True):
            st.subheader("해양 뉴스 & 칼럼")
            st.write("해양 생태계가 보내는 변화의 신호")
            st.page_link("pages/news.py" if role != "guest" else "pages/login.py", label="더 보기" if role != "guest" else "로그인 후 더 보기")
        st.caption(f"현재 모드: {'운영자' if role == 'admin' else '회원' if role == 'member' else '비회원'} · {user}")
        if role == "guest":
            st.page_link("pages/login.py", label="로그인 / 회원가입")


def login() -> None:
    header("SCR-17", "로그인 · 회원가입", "프로필을 만들고 관찰 기록을 이어가세요.")
    if not st.session_state.get("settings", {}).get("app", {}).get("demo_mode", True):
        st.warning("운영 모드에서는 데모 인증이 꺼져 있습니다. 인증 제공자를 연결한 뒤 이용할 수 있습니다.")
        return
    st.info("시안의 인증 화면은 미정의입니다. 이 실행본은 화면 검토용 데모 계정을 사용합니다.")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("로그인")
        with st.form("login_form"):
            email = st.text_input("이메일", value="demo@sea-info.local")
            password = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
        if submitted:
            if not email or "@" not in email or not password:
                st.error("이메일과 비밀번호를 확인해 주세요.")
            else:
                st.session_state.email = email
                st.session_state.role = "admin" if email.startswith("admin") else "member"
                st.toast("로그인되었습니다.")
                st.switch_page("pages/home.py")
    with right, st.container(border=True):
        st.subheader("회원가입")
        with st.form("signup_form"):
            new_email = st.text_input("가입 이메일", key="signup_email")
            nickname = st.text_input("닉네임", key="signup_nickname")
            character = st.selectbox("해양생물 캐릭터", ["🐠 흰동가리", "⭐ 불가사리", "🦀 소라게", "🐙 문어"])
            ok = st.form_submit_button("데모 계정 만들기", use_container_width=True)
        if ok:
            if "@" not in new_email or not nickname.strip():
                st.error("올바른 이메일과 닉네임을 입력해 주세요.")
            else:
                st.session_state.email, st.session_state.nickname = new_email, nickname.strip()
                st.session_state.character = character
                st.session_state.role = "member"
                st.toast("데모 계정이 준비되었습니다.")
                st.switch_page("pages/home.py")


def explore() -> None:
    header("SCR-02 · SCR-03", "사진 촬영 · 앨범 선택", "사진 한 장으로 해양생물을 함께 탐구해요.")
    st.warning("운영 환경에서 Gemini를 연결하면 사진이 Google API로 전송됩니다. 얼굴·개인정보가 보이는 사진은 올리지 마세요. 현재 개발 데모에서는 파일을 외부로 보내지 않습니다.")
    file_col, camera_col = st.columns(2)
    uploaded = file_col.file_uploader("앨범에서 사진 선택", type=["jpg", "jpeg", "png", "webp"])
    camera = camera_col.camera_input("사진 촬영")
    upload = uploaded or camera
    if upload:
        st.image(upload, caption=upload.name, use_container_width=True)
        upload.seek(0)
        try:
            upload_bytes, _mime = prepare_image(
                upload.getvalue(), upload.name,
                max_bytes=st.session_state.settings["uploads"]["max_bytes"],
                max_dimension=st.session_state.settings["uploads"]["max_image_dimension"],
            )
        except ValueError as exc:
            upload_bytes = b""
            st.error(str(exc))
    else:
        upload_bytes = b""
    demo_mode = st.session_state.get("settings", {}).get("app", {}).get("demo_mode", True)
    if not demo_mode:
        st.warning("실제 Gemini 분석 어댑터는 아직 연결되지 않았습니다. 운영 API를 연결하기 전까지 분석은 중지됩니다.")
    consent = st.checkbox("AI 분석을 위해 사진을 Gemini API로 전송하는 데 동의합니다.")
    st.caption("동의는 게시물 공개 및 운영자 사진 활용 동의와 별도로 기록됩니다. 분석하지 않고 게시판을 이용할 수 있습니다.")
    role, user = identity()
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    if st.session_state.get("analysis_day") != today:
        st.session_state.analysis_day = today
        st.session_state.analysis_count = 0
    ai_cfg = st.session_state.get("settings", {}).get("ai", {})
    limit = ai_cfg.get("daily_limit_guest", 3) if role == "guest" else ai_cfg.get("daily_limit_member", 20)
    remaining = max(0, limit - st.session_state.get("analysis_count", 0))
    st.caption(f"오늘 남은 AI 분석 횟수: {remaining}회 (데모 한도)")
    cols = st.columns([1, 1, 2])
    if cols[0].button("예시 이미지로 둘러보기"):
        st.session_state.demo_species = random.choice(SPECIES)
        st.rerun()
    can_analyze = bool(upload_bytes or st.session_state.get("demo_species"))
    if cols[1].button("사진 확인 후 분석하기", type="primary", disabled=not can_analyze or not consent or remaining <= 0 or not demo_mode):
        if upload and upload.size > 10 * 1024 * 1024:
            st.error("사진은 10MB 이하로 올려 주세요.")
        else:
            started = time.perf_counter()
            with st.spinner("사진에서 생물 특징을 살펴보고 있어요..."):
                photo_hash = hashlib.sha256(upload_bytes).hexdigest() if upload else "demo"
                item = st.session_state.get("demo_species") or SPECIES[int(photo_hash[:2], 16) % len(SPECIES)]
                st.session_state.analysis_result = item
                st.session_state.analysis_count = st.session_state.get("analysis_count", 0) + 1
                store.log_analysis(user, "success", int((time.perf_counter() - started) * 1000))
                store.save_consent(user, "ai_transfer", True)
    if st.session_state.get("analysis_result"):
        render_analysis(st.session_state.analysis_result)


def render_analysis(item: dict) -> None:
    st.divider()
    st.subheader("SCR-03 · 생물 분석 결과")
    with st.container(border=True):
        st.markdown(f"## {item['emoji']} {item['name']}")
        st.caption(item["scientific"])
        st.write(f"AI 추정 확신도 · {int(item['confidence']*100)}%")
        st.progress(item["confidence"])
        st.warning("AI 판별은 틀릴 수 있습니다. 확인이 필요합니다.")
        st.caption("데모 분석 결과이며 실제 Gemini 호출 결과가 아닙니다.")
    habitat, diet, ecology, questions = st.tabs(["서식지", "먹이", "생태 정보", "연관 질문"])
    habitat.write(item["habitat"])
    diet.write(item["diet"])
    ecology.write(item["summary"])
    with questions:
        prompts = [f"{item['name']}는 어디에서 관찰할 수 있나요?", f"{item['name']}를 안전하게 관찰하는 방법은?", f"{item['name']}와 함께 사는 생물이 있나요?"]
        for index, question in enumerate(prompts):
            if st.button(question, key=f"related_{item['name']}_{index}"):
                st.session_state.related_question = question
        if st.session_state.get("related_question") in prompts:
            st.info("탐구 답변 예시입니다. 개발 데모에서는 Gemini 텍스트 응답을 호출하지 않습니다. 생물을 만지지 말고 서식지를 훼손하지 않는 거리에서 관찰해 주세요.")
    if st.button("관찰 게시물 작성 · SCR-04", type="primary"):
        st.session_state.selected_species = item["name"]
        st.switch_page("pages/community.py")


def community() -> None:
    header("SCR-04 · SCR-05 · SCR-06", "커뮤니티", "관찰 기록과 바다 이야기를 나눠요.")
    all_tab_names = ["공지사항", "자유 소통", "생물 질문방", "사진 이야기", "관찰 모음"]
    board_status = st.session_state.get("board_status", {name: True for name in all_tab_names})
    tab_names = all_tab_names if st.session_state.get("role") == "admin" else [name for name in all_tab_names if board_status.get(name, True)]
    if not tab_names:
        st.info("현재 운영 중인 게시판이 없습니다.")
        return
    default_tab = "자유 소통" if "자유 소통" in tab_names else tab_names[0]
    selected_tab = st.segmented_control("게시판", tab_names, default=default_tab, key="board_type") or default_tab
    if st.session_state.get("role") == "guest":
        st.info("게시물 작성은 로그인 회원만 이용할 수 있습니다.")
        st.page_link("pages/login.py", label="로그인 / 회원가입")
    else:
      with st.expander("+ 글쓰기 / 관찰 등록", expanded=bool(st.session_state.get("selected_species"))):
        st.caption("분석 결과가 있으면 생물 이름을 자동으로 채웁니다. 게시판 등록 성공 시 수족관에 자동 추가됩니다.")
        role, user = identity()
        with st.form("post_form"):
            species_names = [s["name"] for s in SPECIES]
            default_species = st.session_state.get("selected_species", species_names[0])
            species = st.selectbox("생물 이름", species_names, index=species_names.index(default_species) if default_species in species_names else 0)
            title = st.text_input("제목", placeholder="관찰한 생물의 이야기를 적어주세요")
            body = st.text_area("관찰 이야기", placeholder="어디에서, 어떻게 만났나요?", height=120)
            region = st.selectbox("관찰 지역", ["제주", "부산", "강릉", "인천", "기록하지 않음"])
            visibility = st.selectbox("관찰 위치 공개", ["비공개", "대략 공개", "정확 공개"])
            st.caption("기본 위치 공개는 비공개입니다. 공개 시 원본 GPS·EXIF는 다른 사용자에게 전달되지 않습니다.")
            is_public = st.checkbox("관찰 게시물을 커뮤니티에 공개합니다.", value=True)
            photo = st.file_uploader("관찰 사진 (선택)", type=["jpg", "jpeg", "png", "webp"])
            public_photo = st.checkbox("첨부 사진을 다른 사용자에게 공개합니다.") if photo else False
            operator_photo = st.checkbox("운영자 품질 개선을 위한 사진 활용에 동의합니다. (선택)") if photo else False
            st.caption("운영자 사진 활용은 서비스 운영·품질 개선 범위입니다. 동의 여부는 별도로 저장되며 추후 철회할 수 있습니다.")
            submit = st.form_submit_button("내용 확인 후 게시", type="primary")
        if submit:
            if not title.strip() or not body.strip():
                st.error("제목과 관찰 이야기를 입력해 주세요.")
            elif photo and not public_photo:
                st.error("사진을 공개하려면 게시물 공개·사진 노출 동의가 필요합니다. 사진 없이 텍스트 관찰은 게시할 수 있습니다.")
            else:
                try:
                    post_id = store.create_observation(title=title, body=body, species=species, author=user, region=region,
                                                       visibility=visibility, is_public=is_public,
                                                       board_type=selected_tab,
                                                       public_photo=public_photo, operator_photo=operator_photo,
                                                       photo_blob=prepare_image(photo.getvalue(), photo.name,
                                                           max_bytes=st.session_state.settings["uploads"]["max_bytes"],
                                                           max_dimension=st.session_state.settings["uploads"]["max_image_dimension"])[0] if photo else None,
                                                       post_points=st.session_state.settings["points"]["post_create"],
                                                       daily_points_cap=st.session_state.settings["points"]["daily_cap"])
                    st.session_state.last_post_id = post_id
                    st.session_state.selected_species = ""
                    st.success("게시물이 등록됐고 수족관에 생물이 추가되었습니다. · SCR-16")
                except Exception as exc:
                    st.error(f"저장에 실패했습니다: {exc}")
    all_posts = store.observations()
    role, user = identity()
    posts = [p for p in all_posts if (p["is_public"] or p["author"] == user or role == "admin") and
             (not p.get("is_hidden") or p["author"] == user or role == "admin") and
             (selected_tab == "관찰 모음" or p["board_type"] == selected_tab)]
    if not posts:
        st.info(f"{selected_tab} 게시판에 공개된 기록이 없습니다.")
    species_filter = st.selectbox("생물 필터", ["전체"] + sorted({p["species"] for p in posts}))
    sort_by = st.selectbox("정렬", ["최신순", "인기순"])
    if species_filter != "전체":
        posts = [p for p in posts if p["species"] == species_filter]
    if sort_by == "인기순":
        posts.sort(key=lambda p: p["likes"], reverse=True)
    for post in posts:
        with st.container(border=True):
            if post.get("photo_blob"):
                st.image(post["photo_blob"], use_container_width=True)
            st.subheader(post["title"])
            location = post["region"] if post["location_visibility"] != "비공개" else "위치 비공개"
            st.caption(f"{post['species']} · {post['author']} · {location} · {post['created_at'][:10]}")
            st.write(post["body"])
            st.caption(f"위치 공개: {post['location_visibility']} · ♡ {post['likes']}")
            if st.button("자세히 보기 · SCR-06", key=f"open_{post['id']}"):
                open_post_detail(post["id"])
            with st.expander(f"작성자 공개 프로필 · SCR-07 ({post['author']})"):
                public_by_author = [p for p in all_posts if p["author"] == post["author"] and p["is_public"]]
                st.write(f"공개 관찰 {len(public_by_author)}건 · 관찰 생물 {len({p['species'] for p in public_by_author})}종")
                public_collection=store.public_species(post["author"])
                if public_collection:
                    st.write("공개 도감: " + " · ".join(public_collection))
                st.caption("비공개 관찰과 나의 수족관 전체는 공개하지 않습니다.")
            role, user = identity()
            if role != "guest":
                if st.button("공감", key=f"like_{post['id']}"):
                    store.toggle_like(post["id"], user)
                    st.toast("공감했습니다.")
                    st.rerun()
            else:
                st.page_link("pages/login.py", label="로그인 후 공감할 수 있습니다.")
            with st.expander(f"댓글 · SCR-06 ({post['id']})"):
                for comment in store.get_comments(post["id"]):
                    st.write(f"**{comment['author']}** · {comment['body']}")
                if role == "guest":
                    st.page_link("pages/login.py", label="로그인 후 댓글을 작성할 수 있습니다.")
                else:
                    with st.form(f"comment_{post['id']}"):
                        comment_text = st.text_input("댓글", key=f"comment_text_{post['id']}")
                        if st.form_submit_button("댓글 등록"):
                            if comment_text.strip():
                                store.add_comment(post["id"], user, comment_text)
                                st.toast("댓글을 등록했습니다.")
                                st.rerun()
            if post["author"] == user or role == "admin":
                with st.expander("관찰 수정 · 삭제"):
                    with st.form(f"edit_{post['id']}"):
                        edit_title = st.text_input("제목", value=post["title"], key=f"edit_title_{post['id']}")
                        edit_body = st.text_area("관찰 이야기", value=post["body"], key=f"edit_body_{post['id']}")
                        edit_visibility = st.selectbox("위치 공개", ["비공개", "대략 공개", "정확 공개"],
                                                       index=["비공개", "대략 공개", "정확 공개"].index(post["location_visibility"]),
                                                       key=f"edit_location_{post['id']}")
                        edit_public = st.checkbox("게시물 공개", value=bool(post["is_public"]), key=f"edit_public_{post['id']}")
                        save_edit = st.form_submit_button("수정 저장")
                    if save_edit:
                        if not edit_title.strip() or not edit_body.strip():
                            st.error("제목과 내용을 입력해 주세요.")
                        else:
                            store.update_observation(post["id"], user, title=edit_title, body=edit_body,
                                                     visibility=edit_visibility, is_public=edit_public, is_admin=role == "admin")
                            st.toast("관찰 기록을 수정했습니다.")
                            st.rerun()
                    confirmed = st.checkbox("이 관찰 기록을 삭제하겠습니다.", key=f"confirm_delete_{post['id']}")
                    if st.button("관찰 삭제", key=f"delete_{post['id']}", disabled=not confirmed):
                        store.delete_observation(post["id"], user, is_admin=role == "admin")
                        st.toast("관찰 기록을 삭제했습니다.")
                        st.rerun()


def aquarium() -> None:
    if not require_member():
        return
    header("SCR-08 · SCR-09", "나의 수족관", "모은 생물과 공개 도감을 관리해요.")
    role, user = identity()
    posts = store.observations()
    species_by_name = {x["name"]: x for x in SPECIES}
    owned = sorted({p["species"] for p in posts if p["author"] == user})
    if not owned:
        st.info("아직 기록한 생물이 없습니다. 관찰 게시물을 작성하면 수족관에 자동으로 추가됩니다.")
    search = st.text_input("생물 검색")
    species_names = [s for s in sorted(species_by_name) if search.casefold() in s.casefold()]
    cols = st.columns(3)
    for i, name in enumerate(species_names):
        item = species_by_name[name]
        with cols[i % 3], st.container(border=True):
            st.markdown(f"## {item['emoji']}  {name}")
            st.caption("수집 완료 · 공개 설정은 기본 비공개" if name in owned else "🔒 아직 만나지 못한 생물")
            if name in owned and st.button("도감 상세 · SCR-09", key=f"aquarium_{name}"):
                st.session_state.aquarium_species = name
                st.rerun()
    current = st.session_state.get("aquarium_species")
    if current:
        item = species_by_name[current]
        with st.container(border=True):
            st.subheader(f"{item['emoji']} {current} · 나의 바다 도감")
            st.write(f"**서식지** {item['habitat']}  ")
            st.write(f"**먹이** {item['diet']}  ")
            st.write(f"**생태** {item['summary']}")
            st.write("최근 관찰 기록")
            for post in posts:
                if post["species"] == current and post["author"] == user:
                    st.write(f"{post['created_at'][:10]} · {post['title']} · {post['region']}")
            is_public=st.toggle("다른 사용자의 공개 도감에 표시",value=store.aquarium_is_public(user,current),key=f"public_{current}")
            store.set_aquarium_public(user,current,is_public)
            st.caption("사진 활용 동의 철회 시 공개 노출을 중단합니다.")
            confirm = st.checkbox("이 생물의 사진 공개 동의를 철회합니다.", key=f"withdraw_confirm_{current}")
            if st.button("사진 공개 동의 철회", key=f"withdraw_{current}", disabled=not confirm):
                count = store.withdraw_species_photos(user, current)
                st.success(f"동의를 철회했습니다. 사진 {count}건의 공개를 중단했습니다.")
                st.rerun()


def games() -> None:
    header("SCR-10 · SCR-11 · SCR-12", "게임 & 퀴즈", "짧은 게임으로 바다 생물을 만나보세요.")
    st.info("데모 모드: 회원 게임 점수는 SQLite에 기록됩니다. 활동 포인트와는 별도로 집계합니다.")
    a, b = st.columns(2)
    with a, st.container(border=True):
        st.subheader("🐬 해양생물 퀴즈")
        st.caption("획득 점수 Top 5")
        quiz_top=store.game_top("quiz")
        quiz_rows=[{"순위":i+1,"닉네임":r["user_id"],"점수":r["score"]} for i,r in enumerate(quiz_top)] or [{"순위": i+1, "닉네임": n, "점수": score} for i,(n,score) in enumerate([("바다탐험가",100),("파도소리",90),("해변산책러",80),("바다연구가",70),("푸른바다",60)])]
        safe_dataframe(quiz_rows, hide_index=True, use_container_width=True)
        if st.button("퀴즈 시작 · SCR-11", type="primary"):
            st.session_state.quiz_open = True
            st.session_state.quiz_index = 0
            st.session_state.quiz_score = 0
    with b, st.container(border=True):
        st.subheader("🧩 생물 사진 퍼즐")
        st.caption("획득 점수 Top 5")
        puzzle_top=store.game_top("puzzle")
        puzzle_rows=[{"순위":i+1,"닉네임":r["user_id"],"점수":r["score"]} for i,r in enumerate(puzzle_top)] or [{"순위": i+1, "닉네임": n, "점수": score} for i,(n,score) in enumerate([("바다별",100),("조개친구",90),("바다연구가",80),("파도소리",60),("해변산책러",50)])]
        safe_dataframe(puzzle_rows, hide_index=True, use_container_width=True)
        if st.button("퍼즐 시작 · SCR-12"):
            st.session_state.puzzle_open = True
            st.session_state.puzzle = ["🪸", "🐠", "🐬", "🦪"]
            st.session_state.puzzle_moves = 0
            st.session_state.puzzle_score_saved = False
    if st.session_state.get("quiz_open"):
        idx = st.session_state.get("quiz_index", 0)
        question, options, answer, explanation = QUIZ[idx]
        with st.container(border=True):
            st.markdown(f"### 해양생물 퀴즈 · {idx+1}/2")
            st.write(question)
            choice = st.radio("답을 선택하세요", options, key=f"quiz_choice_{idx}")
            if st.button("답 확인", key=f"quiz_answer_{idx}"):
                good = options.index(choice) == answer
                st.session_state.quiz_score += 50 if good else 0
                st.success(explanation) if good else st.info(explanation)
                if idx + 1 >= len(QUIZ):
                    st.session_state.quiz_open = False
                    st.success(f"완료 점수: {st.session_state.quiz_score}점")
                    if st.session_state.get("role") != "guest":
                        store.save_game(identity()[1], "quiz", st.session_state.quiz_score)
                else:
                    st.session_state.quiz_index += 1
                    st.rerun()
            if st.button("게임 닫기", key="close_quiz"):
                st.session_state.quiz_open = False
                st.rerun()
    if st.session_state.get("puzzle_open"):
        with st.container(border=True):
            st.markdown("### 생물 사진 퍼즐 · 2×2 예시")
            st.caption("두 조각을 차례로 선택해 위치를 바꿉니다. 목표 순서: 🐠 🪸 🦪 🐬")
            items = st.session_state.get("puzzle", ["🪸", "🐠", "🐬", "🦪"])
            grid = st.columns(2)
            for i, value in enumerate(items):
                if grid[i // 2].button(f"{value} · {i+1}", key=f"puzzle_{i}", use_container_width=True):
                    selected = st.session_state.get("puzzle_selected")
                    if selected is None:
                        st.session_state.puzzle_selected = i
                    else:
                        items[selected], items[i] = items[i], items[selected]
                        st.session_state.puzzle = items
                        st.session_state.puzzle_selected = None
                        st.session_state.puzzle_moves += 1
                        st.rerun()
            st.write(f"이동 횟수: {st.session_state.get('puzzle_moves', 0)}")
            if items == ["🐠", "🪸", "🦪", "🐬"]:
                st.success("퍼즐을 완성했습니다!")
                if not st.session_state.get("puzzle_score_saved"):
                    if st.session_state.get("role") != "guest":
                        store.save_game(identity()[1], "puzzle", max(0, 100 - st.session_state.get("puzzle_moves", 0)))
                    st.session_state.puzzle_score_saved=True
            p, q = st.columns(2)
            if p.button("초기화"):
                st.session_state.puzzle = ["🪸", "🐠", "🐬", "🦪"]
                st.session_state.puzzle_moves = 0
                st.session_state.puzzle_score_saved = False
                st.rerun()
            if q.button("게임 닫기"):
                st.session_state.puzzle_open = False
                st.rerun()


def news() -> None:
    header("SCR-13", "해양 뉴스 · 칼럼", "바다와 수산 분야의 소식을 만나보세요.")
    st.caption("출처 확인을 마치기 전까지는 샘플 콘텐츠로 표시합니다.")
    articles = [
        ("해양 생태계가 보내는 변화의 신호", "해양 생물과 서식지 변화를 이해하는 짧은 소개입니다.", "Sea-Info 편집팀", 250),
        ("우리 바다를 지키는 작은 관찰", "시민 관찰 기록을 생태 교육에 연결하는 방법입니다.", "해양 칼럼", 220),
        ("바다 생물과 함께하는 지속 가능한 미래", "해양 보호를 위한 일상 속 실천을 알아봅니다.", "Sea-Info 편집팀", 190),
        ("연안의 계절과 새로운 생명", "계절에 따라 달라지는 연안 생물을 살펴봅니다.", "해양 칼럼", 160),
        ("해양 보호를 위한 다양한 노력", "보호구역과 시민 참여의 역할을 정리합니다.", "Sea-Info 편집팀", 130),
    ]
    for idx, (title, summary, source, views) in enumerate(articles, 1):
        with st.container(border=True):
            st.caption(f"{idx:02d} · 많이 읽은 소식")
            st.subheader(title)
            st.write(summary)
            st.caption(f"출처: {source} · 예시 조회수 {views}")
            with st.expander("요약 및 출처"):
                st.write("실제 원문 수집은 배포 설정에서 뉴스 연동을 활성화한 뒤 출처·이용 조건을 확인해야 합니다.")


def reports() -> None:
    header("SCR-14", "제보 · 건의", "소중한 의견을 남겨주시면 확인 후 안내해 드릴게요.")
    entry, lookup = st.columns(2)
    with entry, st.container(border=True):
        st.subheader("새로운 문의 접수")
        with st.form("report_form"):
            kind = st.selectbox("유형", ["오류 제보", "기능 건의"])
            title = st.text_input("제목")
            body = st.text_area("내용", height=150)
            email = st.text_input("처리 결과를 받을 이메일")
            submitted = st.form_submit_button("문의 접수하기", type="primary")
        if submitted:
            if not title.strip() or len(body.strip()) < 10 or "@" not in email:
                st.error("제목, 10자 이상의 내용, 올바른 이메일을 입력해 주세요.")
            else:
                receipt = store.save_report(kind, title, body, email)
                st.session_state.last_receipt = receipt
                st.success(f"접수되었습니다. 접수번호: {receipt}")
                st.caption("데모 모드에서는 Jira 등록·이메일 발송을 실행하지 않습니다.")
    with lookup, st.container(border=True):
        st.subheader("비회원 문의 확인")
        st.write("이메일과 접수번호로 처리 상태를 확인할 수 있습니다.")
        email = st.text_input("이메일", key="lookup_email")
        receipt = st.text_input("접수번호", value=st.session_state.get("last_receipt", ""))
        if st.button("접수 확인하기"):
            found = store.lookup_report(receipt, email) if receipt and email else None
            if found:
                st.info(f"{found['status']} · {found['kind']} · {found['title']}")
            else:
                st.warning("일치하는 데모 접수 내역을 찾지 못했습니다.")


def dashboard() -> None:
    if not require_member():
        return
    role, user = identity()
    if role == "admin":
        admin_dashboard()
        return
    header("SCR-18", "회원 프로필 · 포인트", "관찰 활동과 보유 포인트를 확인해요.")
    posts = store.observations()
    mine = [p for p in posts if p["author"] == user]
    collections = {p["species"] for p in mine}
    values = [("내 관찰 수",len(mine)),("수집 종 수",len(collections)),("보유 포인트",store.get_points(user)),
              ("받은 댓글 수",sum(len(store.get_comments(p["id"])) for p in mine)),
              ("오늘 남은 AI",max(0,20-st.session_state.get("analysis_count",0)))]
    for col,(label,value) in zip(st.columns(5),values):
        col.metric(label,value)
    a,b = st.columns(2)
    with a, st.container(border=True):
        st.subheader("월별 관찰 추이")
        safe_line_chart({"관찰": [1,2,2,3,4,5]}, x_label="월", y_label="관찰 수")
    with b, st.container(border=True):
        st.subheader("분류군별 수집 현황")
        safe_bar_chart({"종 수": {"어류":2,"무척추동물":3,"해조류":1}})
    st.subheader("최근 관찰 기록")
    safe_dataframe([{k:v for k,v in post.items() if k != "photo_blob"} for post in mine], use_container_width=True, hide_index=True)
    st.progress(min(1.0, len(collections)/12), text=f"수집 진행률 {len(collections)}/12 종")


def admin_dashboard() -> None:
    header("ADM-01 · ADM-03", "운영자 대시보드", "게시판·제보·연동 상태를 관리합니다.")
    posts = store.observations()
    with store.connect() as con:
        reports_count = con.execute("SELECT COUNT(*) FROM reports WHERE status='접수'").fetchone()[0]
    values=[("전체 회원 수",128),("오늘 게시물 수",len(posts)),("오늘 AI 호출 수",st.session_state.get("analysis_count",0)),("미처리 제보",reports_count)]
    for c,(k,v) in zip(st.columns(4),values): c.metric(k,v)
    ai,content = st.tabs(["AI 분석 현황", "게시판·제보·외부 연동"])
    with ai:
        with st.expander("AI 한도 및 포인트 정책 설정"):
            settings=st.session_state.settings
            with st.form("limits_and_points"):
                member_limit=st.number_input("회원 AI 하루 한도",min_value=0,max_value=1000,value=int(settings["ai"]["daily_limit_member"]))
                guest_limit=st.number_input("비회원 AI 하루 한도",min_value=0,max_value=1000,value=int(settings["ai"]["daily_limit_guest"]))
                post_points=st.number_input("관찰 등록 포인트",min_value=0,max_value=1000,value=int(settings["points"]["post_create"]))
                daily_cap=st.number_input("하루 포인트 상한",min_value=0,max_value=10000,value=int(settings["points"]["daily_cap"]))
                saved=st.form_submit_button("정책 저장 (현재 세션)")
            if saved:
                settings["ai"]["daily_limit_member"]=int(member_limit)
                settings["ai"]["daily_limit_guest"]=int(guest_limit)
                settings["points"]["post_create"]=int(post_points)
                settings["points"]["daily_cap"]=int(daily_cap)
                st.toast("정책을 현재 세션에 저장했습니다.")
        for c,(k,v) in zip(st.columns(4),[("성공",18),("실패",1),("한도 초과(429)",2),("캐시 적중률","42%")]): c.metric(k,v)
        l,r=st.columns(2)
        safe_line_chart({"호출": [4,7,6,10,5,8,12]}, container=l)
        safe_bar_chart({"AI 추정 확신도": {"0~40%":2,"40~70%":6,"70~90%":9,"90~100%":4}}, container=r)
        st.caption("응답 시간 1.2초 예시 · AI 전송 동의율 68% · 사진 활용 동의율 45%")
    with content:
        st.subheader("게시판 설정 · ADM-01")
        with st.form("board_settings"):
            board = st.text_input("게시판 이름", "바다 이야기")
            kind=st.selectbox("게시판 유형",["일반형","사진형","질문형"])
            access=st.selectbox("읽기 / 쓰기 권한",["전체 공개 / 로그인 회원 작성","로그인 회원 전용"])
            st.multiselect("입력 항목",["제목","본문","사진","위치","날짜"],default=["제목","본문"])
            save=st.form_submit_button("게시판 설정 저장")
        if save:
            st.success(f"{board} 설정을 이 세션에 저장했습니다. ({kind}, {access})")
        st.subheader("게시판 운영 상태")
        statuses=st.session_state.setdefault("board_status",{name:True for name in ["공지사항","자유 소통","생물 질문방","사진 이야기","관찰 모음"]})
        for board_name in ["공지사항","자유 소통","생물 질문방","사진 이야기","관찰 모음"]:
            statuses[board_name]=st.toggle(f"{board_name} 운영 중",value=statuses.get(board_name,True),key=f"board_active_{board_name}")
        with st.expander("사용자 정의 항목 추가 · ADM-02"):
            with st.form("custom_field"):
                name=st.text_input("항목 이름")
                field_type=st.selectbox("유형",["짧은 글","긴 글","숫자","날짜","단일 선택","복수 선택"])
                if st.form_submit_button("추가"):
                    st.success(f"{name or '새 항목'} · {field_type} (데모 저장)")
        st.subheader("외부 연동 상태 · ADM-03")
        cfg=st.session_state.get("settings",{}).get("integrations",{})
        ai_cfg=st.session_state.get("settings",{}).get("ai",{})
        rows=[{"서비스":n,"상태":"키 설정됨 · 어댑터 미연결" if configured else "데모 / 미연결"} for n,configured in
              [("Supabase",bool(cfg.get("supabase_url") and cfg.get("supabase_anon_key"))),
               ("Gemini",bool(ai_cfg.get("api_key"))),
               ("Redis",bool(cfg.get("redis_url"))),
               ("Jira",bool(cfg.get("jira_api_token") and cfg.get("jira_url"))),
               ("해양 관측 API",bool(cfg.get("marine_api_key")))]]
        safe_dataframe(rows, hide_index=True, use_container_width=True)
        st.caption("API 키·비밀번호는 화면에 표시하지 않습니다. 운영 설정 파일과 배포 Secret에 분리합니다.")
        st.subheader("제보·건의 처리")
        reports = store.list_reports()
        if not reports:
            st.info("접수된 제보와 건의가 없습니다.")
        for report in reports:
            with st.container(border=True):
                st.write(f"**{report['kind']} · {report['title']}**")
                st.caption(f"{report['receipt']} · {report['email']} · {report['created_at'][:10]}")
                st.write(report["body"])
                choices=["접수","검토 중","Jira 등록 승인","반려","완료"]
                current=report["status"] if report["status"] in choices else "접수"
                next_status=st.selectbox("처리 상태",choices,index=choices.index(current),key=f"report_status_{report['receipt']}")
                if st.button("상태 저장",key=f"save_report_{report['receipt']}"):
                    store.update_report_status(report["receipt"],next_status)
                    st.toast("처리 상태를 저장했습니다.")
                    st.rerun()
        st.caption("Jira 등록 승인은 로컬 상태만 변경하며, 실제 Jira 이슈는 만들지 않습니다.")


def profile() -> None:
    if not require_member(): return
    role,user=identity()
    header("SCR-18", "내 프로필 · 포인트", "캐릭터와 공개 닉네임, 활동 기록을 관리합니다.")
    with st.container(border=True):
        st.write(f"**닉네임** {st.session_state.get('nickname',user)} · **이메일** {st.session_state.get('email','demo@sea-info.local')}")
        st.write(f"**캐릭터** {st.session_state.get('character','🐠 흰동가리')} · **등급** 바다 탐험가")
        left,right=st.columns(2)
        with left:
            nickname=st.text_input("닉네임",value=st.session_state.get("nickname",user))
            char=st.selectbox("캐릭터",["🐠 흰동가리","⭐ 불가사리","🦀 소라게","🐙 문어"])
            if st.button("프로필 저장"):
                st.session_state.nickname=nickname
                st.session_state.character=char
                st.toast("프로필이 저장되었습니다.")
            if st.session_state.get("settings",{}).get("app",{}).get("demo_mode"):
                changed_email=st.text_input("변경할 이메일", key="changed_email")
                if st.button("이메일 변경 (데모)"):
                    if "@" not in changed_email:
                        st.error("올바른 이메일을 입력해 주세요.")
                    else:
                        st.session_state.email=changed_email.strip().lower()
                        st.success("데모 세션의 이메일을 바꿨습니다. 실제 인증 메일은 발송되지 않았습니다.")
        with right:
            mine=[p for p in store.observations() if p["author"]==user]
            st.metric("보유 포인트",store.get_points(user))
            st.caption("글 등록, 게임, 댓글 포인트 정책은 운영 설정에서 관리합니다.")
    if st.button("로그아웃"):
        st.session_state.role="guest"
        st.session_state.email=""
        st.switch_page("pages/home.py")
