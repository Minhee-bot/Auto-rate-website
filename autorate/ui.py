"""화면 공통 부품.

표는 st.dataframe 대신 정적 표(st.table)로 보여준다. st.dataframe은 헤더를 캔버스로 그려서
CSS로 색을 바꿀 수 없기 때문이다. 헤더 색과 선은 app.py의 THEME_CSS(stTable 규칙)에서 정한다.
"""

import pandas as pd
import streamlit as st


def show_table(data, **_options):
    """표를 보여준다. 기존 st.dataframe 옵션(width, hide_index)은 받기만 하고 무시한다.

    정렬과 가로 스크롤 상자는 없어진다. 대신 헤더 색을 디자인 시스템(라임)으로 맞출 수 있다.
    """
    styled = data.style if isinstance(data, pd.DataFrame) else data
    st.table(styled.hide(axis="index"))
