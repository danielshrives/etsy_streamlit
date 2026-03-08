import streamlit as st
import psycopg2


def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])
