import streamlit as st
from config import load_settings

settings = load_settings()
st.set_page_config(page_title=settings['app']['name'], page_icon='🌊', layout=settings['ui']['layout'])
st.session_state.setdefault('settings', settings)
st.session_state.setdefault('role', settings['app'].get('default_role', 'guest'))
st.session_state.setdefault('email', '')

with st.sidebar:
    st.title('🌊 Sea-Info Agent')
    st.caption('EXPLORE THE OCEAN')
    if settings['ui'].get('show_demo_role_switcher') and settings['app'].get('demo_mode'):
        modes = {'비회원':'guest', '회원 데모':'member', '운영자 데모':'admin'}
        selected = st.selectbox('화면 권한 미리보기', list(modes), index=list(modes.values()).index(st.session_state.role))
        if modes[selected] != st.session_state.role:
            st.session_state.role = modes[selected]
            st.session_state.email = 'admin@sea-info.local' if modes[selected] == 'admin' else 'demo@sea-info.local' if modes[selected] == 'member' else ''
            st.rerun()
    st.caption(f"실행 환경: {settings['app']['environment']} · {'샘플 데이터' if settings['app']['demo_mode'] else '실서비스 설정'}")

from sea_info import bootstrap
bootstrap.ensure_once()

pages = [
    st.Page('pages/home.py', title='홈', icon='🏠', default=True),
    st.Page('pages/explore.py', title='AI 생물 탐구', icon='🔎'),
    st.Page('pages/community.py', title='커뮤니티', icon='📝'),
    st.Page('pages/aquarium.py', title='나의 수족관', icon='🐠'),
    st.Page('pages/games.py', title='게임 & 퀴즈', icon='🎮'),
    st.Page('pages/news.py', title='해양 뉴스', icon='📰'),
    st.Page('pages/reports.py', title='제보 & 건의', icon='📣'),
    st.Page('pages/dashboard.py', title='마이 대시보드', icon='📊'),
    st.Page('pages/profile.py', title='내 정보', icon='⚙️'),
    st.Page('pages/post_detail.py', title='관찰 상세', icon='🔍'),
]
if st.session_state.role == 'guest':
    pages.append(st.Page('pages/login.py', title='로그인 · 회원가입', icon='👤'))
if st.session_state.role == 'admin':
    pages.append(st.Page('pages/admin.py', title='운영자 대시보드', icon='🛠️'))

page = st.navigation(pages)
page.run()
