from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import random
import string
import os
import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'yerel-gizli-anahtar-123')

# Supabase / PostgreSQL bağlantı URL düzenlemesi
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

if database_url:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'sslmode': 'require'},
        'pool_pre_ping': True
    }

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Giriş Yapabilmek için Kaydolun.'


# --- VERİTABANI MODELLERİ ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.Text, nullable=True)
    phone = db.Column(db.Text, nullable=True)
    password = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    reset_code = db.Column(db.Text, nullable=True)
    media_items = db.relationship('MediaItem', backref='owner', lazy=True, cascade="all, delete-orphan")

class MediaItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    watched = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()
    admin_user = User.query.filter_by(username='admin').first()
    if not admin_user:
        admin_password = os.environ.get('ADMIN_PASSWORD', 'guvenli_gecici_sifre')
        hashed_pw = bcrypt.generate_password_hash(admin_password).decode('utf-8')
        admin = User(username='admin', password=hashed_pw, is_admin=True)
        db.session.add(admin)
        db.session.commit()

def send_email(to_email, code):
    api_key = os.environ.get('BREVO_API_KEY')
    sender_email = os.environ.get('MAIL_PASSWORD')
    
    url = "https://api.brevo.com/v3/smtp/email"
    
    payload = {
        "sender": {"name": "Film Dizi Takip", "email": sender_email},
        "to": [{"email": to_email}],
        "subject": "Şifre Sıfırlama Kodunuz",
        "htmlContent": f"<html><body><h3>Şifre sıfırlama kodunuz:</h3><p><b>{code}</b></p></body></html>"
    }
    
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code not in [200, 201]:
            print(f"Brevo API Hatası: {response.text}")
    except Exception as e:
        flash(f"Mail Gitmedi - Hata: {str(e)}", "danger")
        print(f"E-posta gönderilemedi: {e}")

# --- ROTALAR ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin_panel'))
            return redirect(url_for('index'))
        else:
            flash('Kullanıcı adı veya şifre hatalı!', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        phone = request.form.get('phone')
        
        user_exists = User.query.filter_by(username=username).first()
        if user_exists:
            flash('Bu kullanıcı adı zaten alınmış.', 'danger')
            return redirect(url_for('register'))
        
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, email=email, phone=phone, password=hashed_pw, is_admin=False)
        db.session.add(new_user)
        db.session.commit()
        
        default_item = MediaItem(title="Inception", type="film", watched=False, user_id=new_user.id)
        db.session.add(default_item)
        db.session.commit()
        
        flash('Kayıt başarılı! Şimdi giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    if current_user.is_admin:
        return redirect(url_for('admin_panel'))
        
    media_list = (
        MediaItem.query.filter_by(user_id=current_user.id)
        .order_by(MediaItem.title.asc())
        .all()
    )
    active_tab = request.args.get('type', 'film')
    sub_tab = request.args.get('filter', 'hepsi')

    filtered = []
    for item in media_list:
        if item.type != active_tab:
            continue
        if sub_tab == 'izlenecek' and item.watched:
            continue
        if sub_tab == 'izlenen' and not item.watched:
            continue
        filtered.append(item)

    all_media_dicts = [{"id": i.id, "title": i.title, "type": i.type, "watched": i.watched} for i in media_list]
    filtered_dicts = [{"id": i.id, "title": i.title, "type": i.type, "watched": i.watched} for i in filtered]

    return render_template('index.html', 
                           media_list=filtered_dicts, 
                           all_media=all_media_dicts, 
                           active_tab=active_tab, 
                           sub_tab=sub_tab)

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    users = User.query.all()
    return render_template('admin.html', users=users)

@app.route('/add', methods=['POST'])
@login_required
def add():
    title = request.form.get('title')
    media_type = request.form.get('type')
    if title:
        new_item = MediaItem(title=title.strip(), type=media_type, watched=False, user_id=current_user.id)
        db.session.add(new_item)
        db.session.commit()
    return redirect(url_for('index', type=media_type))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.email = request.form.get('email')
        current_user.phone = request.form.get('phone')
        
        new_password = request.form.get('new_password')
        if new_password:
            current_user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
            
        db.session.commit()
        flash('Bilgileriniz başarıyla güncellendi.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        user = User.query.filter((User.email == identifier) | (User.username == identifier)).first()
        
        if user and user.email:
            code = ''.join(random.choices(string.digits, k=6))
            user.reset_code = code
            db.session.commit()
            
            send_email(user.email, code)
            
            session['reset_user_id'] = user.id
            flash('Sıfırlama kodu e-posta adresinize gönderildi.', 'info')
            return redirect(url_for('verify_code'))
        
        flash('Bu e-posta adresine ait kayıtlı kullanıcı bulunamadı.', 'danger')
    return render_template('forgot_password.html')

@app.route('/verify-code', methods=['GET', 'POST'])
def verify_code():
    if request.method == 'POST':
        entered_code = request.form.get('code')
        user_id = session.get('reset_user_id')
        user = User.query.get(user_id)
        
        if user and user.reset_code and user.reset_code == entered_code:
            login_user(user)
            user.reset_code = None
            db.session.commit()
            flash('Kod doğrulandı! Şimdi şifrenizi değiştirebilirsiniz.', 'success')
            return redirect(url_for('change_password'))
        
        flash('Hatalı veya süresi geçmiş kod!', 'danger')
    return render_template('verify_code.html')

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        if new_password:
            current_user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
            db.session.commit()
            flash('Şifreniz başarıyla değiştirildi.', 'success')
            if current_user.is_admin:
                return redirect(url_for('admin_panel'))
            return redirect(url_for('index'))
    return render_template('change_password.html')

@app.route('/toggle/<int:item_id>')
@login_required
def toggle(item_id):
    item = MediaItem.query.get_or_404(item_id)
    if item.user_id != current_user.id and not current_user.is_admin:
        return "Yetkisiz işlem", 403
    item.watched = not item.watched
    db.session.commit()
    return redirect(url_for('index', type=item.type))

@app.route('/delete/<int:item_id>')
@login_required
def delete(item_id):
    item = MediaItem.query.get_or_404(item_id)
    if item.user_id != current_user.id and not current_user.is_admin:
        return "Yetkisiz işlem", 403
    active_type = item.type
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('index', type=active_type))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
