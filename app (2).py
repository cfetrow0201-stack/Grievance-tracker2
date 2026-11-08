import os

import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Grievance Tracker", page_icon="🛠️", layout="wide")

# ---------------------------------------------------------------------
# Settings (come from Render "Environment" variables, never from GitHub)
# ---------------------------------------------------------------------


def secret(name):
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception:
        return None


SUPABASE_URL = secret("SUPABASE_URL")
SUPABASE_ANON_KEY = secret("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = secret("SUPABASE_SERVICE_KEY")  # admin-only actions

ROLES = ["admin", "committee", "steward", "member"]
ROLE_LABELS = {
    "admin": "Admin",
    "committee": "Grievance Committee",
    "steward": "Steward",
    "member": "Member",
}

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error("The app is not connected to the database yet. "
             "Add SUPABASE_URL and SUPABASE_ANON_KEY in the hosting settings.")
    st.stop()

# ---------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------


def get_client():
    """One database connection PER logged-in person (never shared)."""
    if "sb" not in st.session_state:
        st.session_state.sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return st.session_state.sb


def service_client():
    """Powerful connection. Only used for admin actions, after the admin check."""
    if not SUPABASE_SERVICE_KEY:
        st.error("SUPABASE_SERVICE_KEY is not set in the hosting settings, "
                 "so adding and removing people won't work yet.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def load_profile():
    sb = get_client()
    uid = st.session_state.user.id
    rows = sb.table("profiles").select("*").eq("id", uid).execute().data
    st.session_state.profile = rows[0] if rows else None
    st.session_state.local_name = None
    if rows and rows[0].get("local_id"):
        locs = sb.table("locals").select("name").execute().data
        if locs:
            st.session_state.local_name = locs[0]["name"]


def logout():
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    st.session_state.clear()
    st.rerun()


# ---------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------


def login_screen():
    st.title("🛠️ Grievance Tracker")
    st.caption("Members only. Log in with the email and password your local gave you.")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        ok = False
        try:
            res = get_client().auth.sign_in_with_password(
                {"email": email.strip(), "password": password}
            )
            st.session_state.user = res.user
            load_profile()
            ok = True
        except Exception:
            st.error("Login failed. Check your email and password.")
        if ok:
            st.rerun()


def pending_screen():
    st.title("Almost there")
    st.warning("Your account has been created but has not been approved yet. "
               "Ask your local's admin to activate it.")
    if st.button("Log out"):
        logout()


def home_page(profile):
    name = profile.get("full_name") or profile.get("email")
    st.title(f"Welcome, {name}")
    st.write(f"**Role:** {ROLE_LABELS.get(profile['role'], profile['role'])}")
    st.info("Coming next: grievance tracking, the deadline calendar, "
            "the searchable contract and handbook, and reminder emails.")


def change_password_page():
    st.title("Change password")
    with st.form("pw"):
        new1 = st.text_input("New password", type="password")
        new2 = st.text_input("Type it again", type="password")
        submitted = st.form_submit_button("Change password")
    if submitted:
        if len(new1) < 10:
            st.error("Use at least 10 characters.")
        elif new1 != new2:
            st.error("The two passwords don't match.")
        else:
            try:
                get_client().auth.update_user({"password": new1})
                st.success("Password changed.")
            except Exception as e:
                st.error(f"Could not change the password: {e}")


def admin_people_page(profile):
    st.title("People")
    sb = get_client()

    # ----- add a person -----
    with st.expander("➕ Add a person", expanded=False):
        with st.form("add_person", clear_on_submit=True):
            email = st.text_input("Email")
            full_name = st.text_input("Full name")
            role = st.selectbox("Role", ROLES, index=ROLES.index("member"),
                                format_func=lambda r: ROLE_LABELS[r])
            temp_pw = st.text_input(
                "Temporary password (at least 10 characters)", type="password")
            add = st.form_submit_button("Create account")
        if add:
            if not email.strip() or len(temp_pw) < 10:
                st.error("Enter an email and a temporary password of 10+ characters.")
            else:
                try:
                    svc = service_client()
                    res = svc.auth.admin.create_user({
                        "email": email.strip(),
                        "password": temp_pw,
                        "email_confirm": True,
                    })
                    svc.table("profiles").update({
                        "full_name": full_name.strip() or None,
                        "role": role,
                        "active": True,
                        "local_id": profile["local_id"],
                    }).eq("id", res.user.id).execute()
                    st.success(f"Created {email.strip()}. Give them the temporary "
                               "password and tell them to change it after logging in.")
                except Exception as e:
                    st.error(f"Could not create the account: {e}")

    # ----- everyone in the system -----
    people = sb.table("profiles").select("*").order("created_at").execute().data
    pending = [p for p in people if not p["active"]]
    active = [p for p in people if p["active"]]

    if pending:
        st.subheader(f"Waiting for approval ({len(pending)})")
    for p in pending:
        _person_editor(p, profile, sb)

    st.subheader(f"Active people ({len(active)})")
    for p in active:
        _person_editor(p, profile, sb)


def _person_editor(p, me, sb):
    label = f"{p.get('full_name') or p['email']}  ·  {ROLE_LABELS.get(p['role'], p['role'])}"
    if not p["active"]:
        label += "  ·  NOT ACTIVE"
    with st.expander(label):
        st.caption(p["email"])
        if p["id"] == me["id"]:
            st.info("This is you. Your own role can't be changed here.")
            return
        with st.form(f"edit_{p['id']}"):
            name = st.text_input("Full name", value=p.get("full_name") or "")
            role = st.selectbox("Role", ROLES, index=ROLES.index(p["role"]),
                                format_func=lambda r: ROLE_LABELS[r])
            is_active = st.checkbox("Active (can log in and see data)", value=p["active"])
            save = st.form_submit_button("Save changes")
        if save:
            try:
                sb.table("profiles").update({
                    "full_name": name.strip() or None,
                    "role": role,
                    "active": is_active,
                    "local_id": me["local_id"],
                }).eq("id", p["id"]).execute()
                st.success("Saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save: {e}")

        st.divider()
        confirm = st.checkbox("Yes, permanently remove this person",
                              key=f"confirm_{p['id']}")
        if st.button("Remove person", key=f"remove_{p['id']}", disabled=not confirm):
            try:
                service_client().auth.admin.delete_user(p["id"])
                st.success("Removed.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not remove: {e}")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

if "user" not in st.session_state:
    login_screen()
    st.stop()

profile = st.session_state.get("profile")
if not profile or not profile["active"]:
    pending_screen()
    st.stop()

is_admin = profile["role"] == "admin"

with st.sidebar:
    st.markdown(f"### {st.session_state.get('local_name') or 'Grievance Tracker'}")
    st.caption(f"{profile.get('full_name') or profile['email']}  \n"
               f"{ROLE_LABELS.get(profile['role'], profile['role'])}")
    pages = ["Home", "Change password"]
    if is_admin:
        pages.insert(1, "Admin: People")
    page = st.radio("Go to", pages, label_visibility="collapsed")
    st.divider()
    if st.button("Log out"):
        logout()

if page == "Home":
    home_page(profile)
elif page == "Change password":
    change_password_page()
elif page == "Admin: People" and is_admin:
    admin_people_page(profile)
