"""Administrator-only document intake. Service credentials remain server-side."""

import os
import re
import sys
from pathlib import Path

import streamlit as st
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingestion import DuplicateDocumentError, create_job  # noqa: E402
from ingestion_worker import schedule_job  # noqa: E402
from document_formats import SUPPORTED_EXTENSIONS  # noqa: E402

st.set_page_config(page_title="Mali Knowledge Hub · Administration", layout="wide")

with st.sidebar:
    st.page_link("app.py", label="Knowledge Hub", width="stretch")


def setting(name):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.environ.get(name, "")


url = setting("SUPABASE_URL")
publishable = setting("SUPABASE_PUBLISHABLE_KEY")
secret = setting("SUPABASE_SECRET_KEY")
admin_emails = {x.strip().casefold() for x in setting("MKH_ADMIN_EMAILS").split(",") if x.strip()}
if not all((url, publishable, secret, admin_emails)):
    st.error("Administration is not configured. Set the server-side admin allowlist and Supabase keys.")
    st.stop()

auth = create_client(url, publishable)
db = create_client(url, secret)
token = st.session_state.get("mkh_admin_access_token")
user = None

# The default Supabase email template sends a magic link. Its implicit-flow
# redirect delivers the short-lived access token in the URL fragment, which is
# available only to browser JavaScript. Keep that short-lived token in this
# tab's session storage so a Render restart can restore the admin session.
# It is cleared on sign-out or failed verification, and never goes into a URL,
# log, or long-lived browser storage.
magic_link_callback = st.components.v2.component(
    name="mkh_admin_magic_link_callback",
    js="""
    export default function({ data, setTriggerValue }) {
      if (window.location.pathname !== "/Administration") return;
      const key = "mkh_admin_access_token";
      if (data.clear) {
        window.sessionStorage.removeItem(key);
        return;
      }
      const fragment = window.location.hash.slice(1);
      const token = fragment ? new URLSearchParams(fragment).get("access_token") : null;
      if (token) {
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        window.sessionStorage.setItem(key, token);
        setTriggerValue("access_token", token);
      } else if (data.needs_restore) {
        const restored = window.sessionStorage.getItem(key);
        if (restored) setTriggerValue("access_token", restored);
      }
    }
    """,
)
callback = magic_link_callback(
    key="mkh_admin_magic_link_callback",
    data={"clear": st.session_state.pop("mkh_admin_clear_browser_token", False),
          "needs_restore": not token},
)
callback_token = callback.get("access_token")
if callback_token:
    try:
        verified = db.auth.get_user(callback_token).user
        if verified and verified.email and verified.email.casefold() in admin_emails:
            st.session_state["mkh_admin_access_token"] = callback_token
            st.session_state.pop("mkh_otp_email", None)
            token = callback_token
        else:
            st.session_state["mkh_admin_auth_error"] = "This account is not authorized for administration."
            st.session_state["mkh_admin_clear_browser_token"] = True
            st.rerun()
    except Exception:
        st.session_state["mkh_admin_auth_error"] = "The sign-in link has expired or could not be verified. Request a new link."
        st.session_state["mkh_admin_clear_browser_token"] = True
        st.rerun()
if token:
    try:
        user = db.auth.get_user(token).user
        if not user or not user.email or user.email.casefold() not in admin_emails:
            user = None
    except Exception:
        user = None
    if not user:
        st.session_state.pop("mkh_admin_access_token", None)
        st.session_state["mkh_admin_clear_browser_token"] = True
        st.rerun()

if not user:
    st.session_state.pop("mkh_admin_access_token", None)
    st.title("Document administration")
    if error := st.session_state.pop("mkh_admin_auth_error", None):
        st.error(error)
    st.write("Sign in with the one-time link sent to an authorized administrator.")
    email = st.text_input("Administrator email").strip().casefold()
    if st.button("Send sign-in link"):
        if email not in admin_emails:
            st.error("This address is not authorized for administration.")
        else:
            try:
                auth.auth.sign_in_with_otp({"email": email, "options": {"should_create_user": True}})
                st.info("Check your email and open the sign-in link. It returns to this administration page.")
            except Exception as exc:
                # Provider messages may contain addresses or request details.
                # Log only a bounded machine code and exception class.
                code = getattr(exc, "code", "")
                code = code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", code) else "unknown"
                print(f"MKH_ADMIN_AUTH_SEND_FAILURE class={type(exc).__name__} code={code}", flush=True)
                if code in {"over_email_send_rate_limit", "over_request_rate_limit"}:
                    st.error("Email sending is temporarily rate-limited. Try again later.")
                else:
                    st.error("The sign-in link could not be sent. Check the Supabase Auth email configuration.")
    st.stop()

st.title("Document administration")
st.caption(f"Signed in as {user.email}")
if st.button("Sign out"):
    st.session_state.pop("mkh_admin_access_token", None)
    st.session_state["mkh_admin_clear_browser_token"] = True
    st.rerun()

with st.container(border=True):
    st.subheader("Add a document")
    st.write("Upload a PDF, Word document (DOC/DOCX), ODT, RTF or text file. The original is stored privately; the document becomes searchable only after extraction, embedding and validation succeed.")
    st.caption("DEV accepts public-source documents. Ready documents are available to public queries.")
    upload = st.file_uploader("Document", type=list(SUPPORTED_EXTENSIONS), max_upload_size=20)
    st.caption("PDFs keep page citations. Other files use original paragraph, table-row or line locations. Images and embedded objects in Word files are not extracted.")
    if st.button("Upload and process", disabled=upload is None, type="primary"):
        try:
            job_id = create_job(db, upload.name, upload.getvalue(), user.id)
            schedule_job(url, secret, setting("OPENAI_API_KEY"), job_id)
            st.success(f"Original stored; processing in the background. Job ID: {job_id}")
            st.caption("Refresh the registry to see the current status. The document is searchable only when ready.")
        except DuplicateDocumentError as exc:
            st.info(str(exc))
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("The upload could not be queued. Review the server configuration and try again.")

try:
    jobs = db.table("ingestion_jobs").select("*").order("uploaded_at", desc=True).limit(1000).execute().data or []
    documents = db.table("documents").select("id,title,organization,publication_date,document_type,geographic_scope,status,version").limit(1000).execute().data or []
except Exception:
    st.error("The corpus registry is unavailable. Apply the V3 migration and verify server configuration.")
    st.stop()

st.subheader("Corpus overview")
if st.button("Refresh registry"):
    st.rerun()
search = st.text_input("Search title or filename")
status_filter = st.selectbox("Ingestion status", ["All", "uploaded", "queued", "processing", "ready", "partially processed", "failed"])
sort = st.selectbox("Sort", ["Newest first", "Oldest first", "Title"])
by_id = {str(d["id"]): d for d in documents}
rows = []
for job in jobs:
    doc = by_id.get(str(job.get("document_id")), {})
    meta = job.get("metadata") or {}
    row = {"job_id": job["id"], "title": doc.get("title") or meta.get("title") or "",
           "filename": job["filename"], "source": doc.get("organization") or meta.get("organization") or "",
           "publication_date": doc.get("publication_date") or meta.get("publication_date") or "",
           "document_type": doc.get("document_type") or meta.get("document_type") or "",
           "geography": doc.get("geographic_scope") or meta.get("geographic_scope") or "",
           "uploaded_at": job["uploaded_at"], "status": job["status"],
           "error": job.get("error") or "", "current_state": doc.get("status") or "unpublished"}
    if search.casefold() not in (row["title"] + " " + row["filename"]).casefold():
        continue
    if status_filter != "All" and job["status"] != status_filter:
        continue
    rows.append(row)
if sort == "Oldest first":
    rows.sort(key=lambda r: r["uploaded_at"])
elif sort == "Title":
    rows.sort(key=lambda r: r["title"].casefold())
st.dataframe(rows, hide_index=True, width="stretch")

if jobs:
    labels = {str(job["id"]): f"{job['filename']} · {job['status']} · {str(job['id'])[:8]}" for job in jobs}
    selected_id = st.selectbox("Inspect a job", list(labels), format_func=lambda key: labels[key])
    selected = next(job for job in jobs if str(job["id"]) == selected_id)
    with st.container(border=True):
        st.write("Status:", selected["status"])
        st.write("Error:", selected.get("error") or "None")
        st.write("Proposed metadata and confidence:")
        st.json({"metadata": selected.get("metadata") or {}, "quality": selected.get("quality") or {}})
        if selected["status"] == "ready":
            current = selected.get("metadata") or {}
            st.write("Review metadata")
            st.caption("Saving a correction reprocesses the stored original and replaces the searchable chunks in one database transaction. This uses embeddings again.")
            fields = {"title": "Title", "organization": "Issuing organisation",
                      "publication_date": "Publication date (YYYY-MM-DD)",
                      "document_type": "Document type", "language": "Language",
                      "geographic_scope": "Geography", "version": "Version"}
            with st.form(f"metadata_{selected_id}"):
                edited = {name: st.text_input(label, value=current.get(name) or "")
                          for name, label in fields.items()}
                submitted = st.form_submit_button("Save corrected metadata")
            if submitted:
                corrections = {name: value for name, value in edited.items()
                               if value.strip() != (current.get(name) or "").strip()}
                if not corrections:
                    st.info("No metadata changes to save.")
                else:
                    if schedule_job(url, secret, setting("OPENAI_API_KEY"),
                                    selected_id, corrections=corrections):
                        st.info("Correction queued. The current document remains searchable until the replacement is ready.")
                    else:
                        st.info("This job is already processing. Refresh the registry to check its status.")
        if selected["status"] in ("failed", "partially processed", "ready"):
            label = "Reprocess original" if selected["status"] == "ready" else "Retry processing"
            if st.button(label, key=f"retry_{selected_id}"):
                if schedule_job(url, secret, setting("OPENAI_API_KEY"), selected_id):
                    st.info("Original queued for background processing. Refresh the registry to inspect its status.")
                else:
                    st.info("This job is already processing. Refresh the registry to inspect its status.")

indexed_ids = {str(job.get("document_id")) for job in jobs if job.get("document_id")}
legacy = [d for d in documents if str(d["id"]) not in indexed_ids]
st.caption(f"{len(jobs)} managed upload jobs · {len(legacy)} pre-V3 corpus documents")
if legacy:
    with st.expander("Existing corpus documents"):
        st.dataframe(legacy, hide_index=True, width="stretch")
