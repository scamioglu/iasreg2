from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
import sqlite3
import os
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet
import secrets

app = Flask(__name__)
load_dotenv()
app.secret_key = os.getenv("SECRET_KEY")

mail = Mail(app)
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER")
app.config["MAIL_PORT"] = os.getenv("MAIL_PORT")
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS")
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

with get_db() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, stage_access INTEGER, reset_token TEXT, reset_expiry TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS stages (id INTEGER PRIMARY KEY, stage_number INTEGER, stage_name TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS forms (id INTEGER PRIMARY KEY, stage_id INTEGER, question TEXT, type TEXT, options TEXT, allow_file_upload INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS parents (id INTEGER PRIMARY KEY, name TEXT, stage_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE IF NOT EXISTS responses (id INTEGER PRIMARY KEY, parent_id INTEGER, form_id INTEGER, answer TEXT, file_url TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")

class User(UserMixin):
    def __init__(self, id, username, password, role, stage_access):
        self.id = id
        self.username = username
        self.password = password
        self.role = role
        self.stage_access = stage_access

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if user:
        return User(user["id"], user["username"], user["password"], user["role"], user["stage_access"])
    return None

@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        conn.close()
        if user:
            user_obj = User(user["id"], user["username"], user["password"], user["role"], user["stage_access"])
            login_user(user_obj)
            if user["role"] == "admin":
                return redirect(url_for("admin"))
            return redirect(url_for("staff"))
        flash("Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        email = request.form["email"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (email,)).fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            expiry = "2025-12-31 23:59:59"
            conn.execute("UPDATE users SET reset_token = ?, reset_expiry = ? WHERE id = ?", (token, expiry, user["id"]))
            conn.commit()
            msg = Message("Password Reset Request", sender=os.getenv("MAIL_USERNAME"), recipients=[email])
            msg.body = f"Click this link to reset your password: http://localhost:5000/reset_password/{token}"
            mail.send(msg)
            flash("Reset link sent to your email")
        else:
            flash("Email not found")
        conn.close()
    return render_template("reset_password.html")

@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password_token(token):
    if request.method == "POST":
        new_password = request.form["password"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE reset_token = ? AND reset_expiry > datetime('now')", (token,)).fetchone()
        if user:
            conn.execute("UPDATE users SET password = ?, reset_token = NULL, reset_expiry = NULL WHERE id = ?", (new_password, user["id"]))
            conn.commit()
            flash("Password reset successfully")
            conn.close()
            return redirect(url_for("login"))
        flash("Invalid or expired token")
        conn.close()
    return render_template("reset_password_token.html")

@app.route("/admin")
@login_required
def admin():
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    conn = get_db()
    users = conn.execute("SELECT * FROM users").fetchall()
    stages = conn.execute("SELECT * FROM stages").fetchall()
    parents = conn.execute("SELECT * FROM parents").fetchall()
    conn.close()
    return render_template("admin.html", users=users, stages=stages, parents=parents)

@app.route("/admin/add_user", methods=["POST"])
@login_required
def add_user():
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    username = request.form["username"]
    password = request.form["password"]
    role = request.form["role"]
    stage_access = request.form["stage_access"]
    conn = get_db()
    conn.execute("INSERT INTO users (username, password, role, stage_access) VALUES (?, ?, ?, ?)", (username, password, role, stage_access))
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, f"Added user: {username}"))
    conn.commit()
    conn.close()
    flash("User added successfully")
    return redirect(url_for("admin"))

@app.route("/admin/delete_user/<int:id>")
@login_required
def delete_user(id):
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (id,))
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, f"Deleted user ID: {id}"))
    conn.commit()
    conn.close()
    flash("User deleted successfully")
    return redirect(url_for("admin"))

@app.route("/admin/add_stage", methods=["POST"])
@login_required
def add_stage():
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    stage_number = request.form["stage_number"]
    stage_name = request.form["stage_name"]
    conn = get_db()
    conn.execute("INSERT INTO stages (stage_number, stage_name) VALUES (?, ?)", (stage_number, stage_name))
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, f"Added stage: {stage_name}"))
    conn.commit()
    conn.close()
    flash("Stage added successfully")
    return redirect(url_for("admin"))

@app.route("/admin/delete_stage/<int:id>")
@login_required
def delete_stage(id):
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    conn = get_db()
    conn.execute("DELETE FROM stages WHERE id = ?", (id,))
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, f"Deleted stage ID: {id}"))
    conn.commit()
    conn.close()
    flash("Stage deleted successfully")
    return redirect(url_for("admin"))

@app.route("/admin/forms")
@login_required
def admin_forms():
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    conn = get_db()
    stages = conn.execute("SELECT * FROM stages").fetchall()
    forms = conn.execute("SELECT f.*, s.stage_name FROM forms f JOIN stages s ON f.stage_id = s.id").fetchall()
    conn.close()
    return render_template("admin_forms.html", stages=stages, forms=forms)

@app.route("/admin/add_form", methods=["POST"])
@login_required
def add_form():
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    stage_id = request.form["stage_id"]
    question = request.form["question"]
    type = request.form["type"]
    options = request.form.get("options", "")
    allow_file_upload = 1 if "allow_file_upload" in request.form else 0
    conn = get_db()
    conn.execute("INSERT INTO forms (stage_id, question, type, options, allow_file_upload) VALUES (?, ?, ?, ?, ?)", (stage_id, question, type, options, allow_file_upload))
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, f"Added form: {question}"))
    conn.commit()
    conn.close()
    flash("Form added successfully")
    return redirect(url_for("admin_forms"))

@app.route("/staff")
@login_required
def staff():
    if current_user.role == "admin":
        return redirect(url_for("admin"))
    conn = get_db()
    stages = conn.execute("SELECT * FROM stages WHERE id = ?", (current_user.stage_access,)).fetchall()
    forms = conn.execute("SELECT * FROM forms WHERE stage_id = ?", (current_user.stage_access,)).fetchall()
    conn.close()
    return render_template("staff.html", stages=stages, forms=forms)

@app.route("/staff/submit_form", methods=["POST"])
@login_required
def submit_form():
    if current_user.role == "admin":
        return redirect(url_for("admin"))
    parent_name = request.form["parent_name"]
    conn = get_db()
    conn.execute("INSERT INTO parents (name, stage_id) VALUES (?, ?)", (parent_name, current_user.stage_access))
    parent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for form_id in request.form:
        if form_id.startswith("form_"):
            form_id = form_id.replace("form_", "")
            answer = request.form[f"form_{form_id}"]
            file_url = None
            if f"file_{form_id}" in request.files:
                file = request.files[f"file_{form_id}"]
                if file:
                    upload_result = cloudinary.uploader.upload(file)
                    file_url = upload_result["url"]
            conn.execute("INSERT INTO responses (parent_id, form_id, answer, file_url) VALUES (?, ?, ?, ?)", (parent_id, form_id, answer, file_url))
    conn.commit()
    conn.close()
    flash("Form submitted successfully")
    return redirect(url_for("staff"))

@app.route("/admin/parents")
@login_required
def admin_parents():
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    conn = get_db()
    parents = conn.execute("SELECT p.*, s.stage_name FROM parents p JOIN stages s ON p.stage_id = s.id").fetchall()
    conn.close()
    return render_template("parents.html", parents=parents)

@app.route("/admin/parent/<int:id>")
@login_required
def parent_detail(id):
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    conn = get_db()
    parent = conn.execute("SELECT p.*, s.stage_name FROM parents p JOIN stages s ON p.stage_id = s.id WHERE p.id = ?", (id,)).fetchone()
    responses = conn.execute("SELECT r.*, f.question, f.type, f.options FROM responses r JOIN forms f ON r.form_id = f.id WHERE r.parent_id = ?", (id,)).fetchall()
    conn.close()
    return render_template("parent_detail.html", parent=parent, responses=responses)

@app.route("/admin/report")
@login_required
def report():
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    conn = get_db()
    parents = conn.execute("SELECT p.*, s.stage_name FROM parents p JOIN stages s ON p.stage_id = s.id").fetchall()
    conn.close()
    return render_template("report.html", parents=parents)

@app.route("/admin/generate_pdf/<int:parent_id>")
@login_required
def generate_pdf(parent_id):
    if current_user.role != "admin":
        return redirect(url_for("staff"))
    conn = get_db()
    parent = conn.execute("SELECT p.*, s.stage_name FROM parents p JOIN stages s ON p.stage_id = s.id WHERE p.id = ?", (parent_id,)).fetchone()
    responses = conn.execute("SELECT r.*, f.question FROM responses r JOIN forms f ON r.form_id = f.id WHERE r.parent_id = ?", (parent_id,)).fetchall()
    conn.close()
    pdf_file = f"report_{parent_id}.pdf"
    doc = SimpleDocTemplate(pdf_file, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []
    elements.append(Paragraph(f"Parent: {parent['name']}", styles["Heading1"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Stage: {parent['stage_name']}", styles["Heading2"]))
    elements.append(Spacer(1, 12))
    data = [["Question", "Answer"]]
    for response in responses:
        data.append([response["question"], response["answer"] or response["file_url"]])
    table = Table(data)
    elements.append(table)
    doc.build(elements)
    return send_file(pdf_file, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True) 
