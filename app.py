from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
import os
import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'SECRET_KEY'

database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
  database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = (
    database_url or 'sqlite:///database.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Giriş Yapabilmek için Kaydolun.'

# --- VERİTABANI MODELLERİ ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    media_items = db.relationship('MediaItem', backref='owner', lazy=True, cascade="all, delete-orphan")

class MediaItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), nullable=False) # 'film' veya 'dizi'
    watched = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


with app.app_context():
  db.create_all()
  admin_user = User.query.filter_by(username='admin').first()
  if not admin_user:
    # Şifreyi doğrudan yazmak yerine sistem ortamından (environment) çekiyoruz
    admin_password = os.environ.get('ADMIN_PASSWORD', 'guvenli_gecici_sifre')
    hashed_pw = bcrypt.generate_password_hash(admin_password).decode('utf-8')
    admin = User(username='admin', password=hashed_pw, is_admin=True)
    db.session.add(admin)
    db.session.commit()

# --- ROTALAR ---

@app.route('/login', methods=['GET', 'POST5' if False else 'GET', 'POST'])
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
        
        user_exists = User.query.filter_by(username=username).first()
        if user_exists:
            flash('Bu kullanıcı adı zaten alınmış.', 'danger')
            return redirect(url_for('register'))
        
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password=hashed_pw, is_admin=False)
        db.session.add(new_user)
        db.session.commit()
        
        # Varsayılan başlangıç filmi ekleyelim
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
        
    media_list = MediaItem.query.filter_by(user_id=current_user.id).all()
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

    # JavaScript için listeyi dict formatına çevirelim
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
