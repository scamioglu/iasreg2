import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io

# Flask uygulamasını başlat
app = Flask(__name__)

# Çevresel değişkenlerden yapılandırma yükle (Render için)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '106098160598010924')  # Güvenlik anahtarı
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')  # E-posta sunucusu
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))  # E-posta portu
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'  # TLS kullanımı
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'scamioglu@gmail.com')  # E-posta adresi
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'zoqg ajmn idqz acgx')  # E-posta şifresi
app.config['UPLOAD_FOLDER'] = 'uploads'  # Dosya yükleme klasörü

# Cloudinary yapılandırması (dosya yükleme için)
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME', 'dmmsncj6x'),
    api_key=os.getenv('CLOUDINARY_API_KEY', '552881692187293'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET', 'rtrD4fSHx-t1ZQOVUF225s8WNG0@')
)

# Flask-Mail ve Flask-Login'i başlat
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'  # Giriş yapmadan erişilemeyen sayfalar için yönlendirme

# Veritabanı bağlantısı fonksiyonu
def get_db():
    conn = sqlite3.connect('database.db')  # SQLite veritabanına bağlan
    conn.row_factory = sqlite3.Row  # Satırları sözlük gibi döndür
    return conn

# Veritabanı tablolarını oluşturma fonksiyonu
def init_db():
    try:
        conn = get_db()
        print("Initializing database...")  # Hata ayıklama için log
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                stage_access INTEGER
            );  -- Kullanıcılar tablosu
            CREATE TABLE IF NOT EXISTS stages (
                id INTEGER PRIMARY KEY,
                stage_number INTEGER,
                stage_name TEXT
            );  -- Aşamalar tablosu
            CREATE TABLE IF NOT EXISTS forms (
                id INTEGER PRIMARY KEY,
                stage_id INTEGER,
                question TEXT NOT NULL,
                type TEXT NOT NULL,
                options TEXT,
                allow_photo_upload BOOLEAN,
                FOREIGN KEY (stage_id) REFERENCES stages(id)
            );  -- Formlar tablosu
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY,
                form_id INTEGER,
                parent_name TEXT NOT NULL,
                answer TEXT,
                file_url TEXT,
                FOREIGN KEY (form_id) REFERENCES forms(id)
            );  -- Yanıtlar tablosu
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                action TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );  -- Günlük kaydı tablosu
            -- Varsayılan admin kullanıcısı ekle
            INSERT OR IGNORE INTO users (username, password, role, stage_access)
            VALUES ('admin@example.com', 'admin123', 'admin', 0);
        """)
        conn.commit()
        print("Database initialized successfully.")  # Başarıyla tamamlandıysa log
        # Tabloyu kontrol et
        users_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';").fetchone()
        if users_table:
            print("Users table exists.")
        else:
            print("Users table does NOT exist!")
        conn.close()
    except Exception as e:
        print(f"Error initializing database: {e}")  # Hata olursa log

# Kullanıcı sınıfı tanımı (Flask-Login için)
class User(UserMixin):
    def __init__(self, id, username, password, role, stage_access):
        self.id = id
        self.username = username
        self.password = password
        self.role = role
        self.stage_access = stage_access

# Kullanıcı yükleme fonksiyonu (Flask-Login)
@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if user:
        return User(user['id'], user['username'], user['password'], user['role'], user['stage_access'])
    return None

# Ana sayfa yönlendirmesi
@app.route('/')
def index():
    return redirect(url_for('login'))

# Giriş sayfası
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and user['password'] == password:  # Şifre kontrolü (düz metin)
            user_obj = User(user['id'], user['username'], user['password'], user['role'], user['stage_access'])
            login_user(user_obj)
            conn = get_db()
            conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (user['id'], 'Logged in'))
            conn.commit()
            conn.close()
            if user['role'] == 'admin':
                return redirect(url_for('admin'))
            return redirect(url_for('staff'))
        flash('Invalid username or password')
    return render_template('login.html')

# Çıkış yapma
@app.route('/logout')
@login_required
def logout():
    conn = get_db()
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, 'Logged out'))
    conn.commit()
    conn.close()
    logout_user()
    return redirect(url_for('login'))

# Admin paneli
@app.route('/admin')
@login_required
def admin():
    if current_user.role != 'admin':
        return redirect(url_for('staff'))
    conn = get_db()
    stages = conn.execute("SELECT * FROM stages").fetchall()
    logs = conn.execute("SELECT l.*, u.username FROM logs l JOIN users u ON l.user_id = u.id").fetchall()
    conn.close()
    return render_template('admin.html', stages=stages, logs=logs)

# Aşama ekleme
@app.route('/admin/add_stage', methods=['POST'])
@login_required
def add_stage():
    if current_user.role != 'admin':
        return redirect(url_for('staff'))
    stage_number = int(request.form['stage_number'])
    stage_name = request.form['stage_name']
    if stage_number < 1:
        flash("Stage number must be 1 or greater")
        return redirect(url_for('admin'))
    conn = get_db()
    conn.execute("INSERT INTO stages (stage_number, stage_name) VALUES (?, ?)", (stage_number, stage_name))
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, f"Added stage: {stage_name}"))
    conn.commit()
    conn.close()
    flash("Stage added successfully")
    return redirect(url_for('admin'))

# Ebeveyn listesi
@app.route('/admin/parents')
@login_required
def admin_parents():
    if current_user.role != 'admin':
        return redirect(url_for('staff'))
    conn = get_db()
    responses = conn.execute("SELECT DISTINCT parent_name FROM responses").fetchall()
    conn.close()
    return render_template('admin_parents.html', responses=responses)

# Ebeveyn detayları
@app.route('/admin/parent/<parent_name>')
@login_required
def admin_parent_details(parent_name):
    if current_user.role != 'admin':
        return redirect(url_for('staff'))
    conn = get_db()
    responses = conn.execute("SELECT r.*, f.question, f.type FROM responses r JOIN forms f ON r.form_id = f.id WHERE r.parent_name = ?", (parent_name,)).fetchall()
    conn.close()
    return render_template('admin_parent_details.html', parent_name=parent_name, responses=responses)

# Raporlar sayfası
@app.route('/admin/reports')
@login_required
def admin_reports():
    if current_user.role != 'admin':
        return redirect(url_for('staff'))
    conn = get_db()
    responses = conn.execute("SELECT DISTINCT parent_name FROM responses").fetchall()
    conn.close()
    return render_template('admin_reports.html', responses=responses)

# Rapor oluşturma
@app.route('/admin/generate_report/<parent_name>')
@login_required
def generate_report(parent_name):
    if current_user.role != 'admin':
        return redirect(url_for('staff'))
    conn = get_db()
    responses = conn.execute("SELECT r.*, f.question, f.type FROM responses r JOIN forms f ON r.form_id = f.id WHERE r.parent_name = ?", (parent_name,)).fetchall()
    conn.close()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    y = 750
    c.drawString(100, y, f"Report for {parent_name}")
    y -= 30
    for response in responses:
        c.drawString(100, y, f"Question: {response['question']}")
        y -= 20
        c.drawString(100, y, f"Answer: {response['answer']}")
        y -= 20
        if response['file_url']:
            c.drawString(100, y, f"File: {response['file_url']}")
            y -= 20
        y -= 10
        if y < 50:
            c.showPage()
            y = 750
    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{parent_name}_report.pdf")

# Formlar sayfası
@app.route('/admin/forms')
@login_required
def admin_forms():
    if current_user.role != 'admin':
        return redirect(url_for('staff'))
    conn = get_db()
    stages = conn.execute("SELECT * FROM stages").fetchall()
    forms = conn.execute("SELECT f.*, s.stage_name FROM forms f JOIN stages s ON f.stage_id = s.id").fetchall()
    conn.close()
    return render_template('admin_forms.html', stages=stages, forms=forms)

# Form ekleme
@app.route('/admin/add_form', methods=['POST'])
@login_required
def add_form():
    if current_user.role != 'admin':
        return redirect(url_for('staff'))
    stage_id = request.form['stage_id']
    question = request.form['question']
    type = request.form['type']
    options = request.form.get('options', '')
    allow_photo_upload = 'allow_photo_upload' in request.form
    conn = get_db()
    conn.execute("INSERT INTO forms (stage_id, question, type, options, allow_photo_upload) VALUES (?, ?, ?, ?, ?)", (stage_id, question, type, options, allow_photo_upload))
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, f"Added form: {question}"))
    conn.commit()
    conn.close()
    flash("Form added successfully")
    return redirect(url_for('admin_forms'))

# Personel sayfası
@app.route('/staff')
@login_required
def staff():
    if current_user.role == 'admin':
        return redirect(url_for('admin'))
    conn = get_db()
    stages = conn.execute("SELECT * FROM stages WHERE id = ?", (current_user.stage_access,)).fetchall()
    forms = conn.execute("SELECT * FROM forms WHERE stage_id = ?", (current_user.stage_access,)).fetchall()
    conn.close()
    return render_template('staff.html', stages=stages, forms=forms)

# Form gönderme
@app.route('/submit_form', methods=['POST'])
@login_required
def submit_form():
    if current_user.role == 'admin':
        return redirect(url_for('admin'))
    parent_name = request.form['parent_name']
    conn = get_db()
    forms = conn.execute("SELECT * FROM forms WHERE stage_id = ?", (current_user.stage_access,)).fetchall()
    for form in forms:
        answer = request.form.get(f'form_{form["id"]}')
        file_url = None
        if form['allow_photo_upload']:
            file = request.files.get(f'file_{form["id"]}')
            if file:
                upload_result = cloudinary.uploader.upload(file)
                file_url = upload_result['url']
        if answer:
            conn.execute("INSERT INTO responses (form_id, parent_name, answer, file_url) VALUES (?, ?, ?, ?)", (form['id'], parent_name, answer, file_url))
    conn.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (current_user.id, f"Submitted form for {parent_name}"))
    conn.commit()
    conn.close()
    msg = Message('Form Submission Confirmation', sender=app.config['MAIL_USERNAME'], recipients=[current_user.username])
    msg.body = f'Your form submission for {parent_name} has been received.'
    mail.send(msg)
    flash("Form submitted successfully")
    return redirect(url_for('staff'))

# Veritabanını başlat (Render'da her deploy'da çalışır)
print("Starting database initialization...")
init_db()
print("Database initialization completed.")

# Uygulamayı Render portunda çalıştır
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))  # Render PORT (varsayılan 10000), yoksa 5000
    app.run(host="0.0.0.0", port=port, debug=True)  # Tüm arayüzlerde dinle
