import os
import requests
from flask import Flask, render_template, request, redirect, url_for, session, g
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
import uuid
from werkzeug.utils import secure_filename
from PIL import Image
from functools import wraps
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')
TMDB_API_KEY = os.getenv('TMDB_API_KEY')

# Debug: Mostra parte da string de conexão (NÃO imprime usuário/senha)
MONGODB_URI = os.getenv('MONGODB_URI')
if MONGODB_URI:
    print('MONGODB_URI começa com:', MONGODB_URI[:30])
else:
    print('MONGODB_URI não encontrada!')

try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000, tls=True, tlsAllowInvalidCertificates=True)
    # Testa conexão imediatamente
    client.admin.command('ping')
    print('Conexão com MongoDB Atlas OK!')
except Exception as e:
    print('Erro ao conectar ao MongoDB Atlas:')
    print(e)
    raise SystemExit('Verifique sua string de conexão, usuário, senha e permissões no Atlas.')

db = client['movie_site']
users_collection = db['users']

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
PROFILE_PIC_FOLDER = os.path.join('static', 'profile_pics')
app.config['PROFILE_PIC_FOLDER'] = PROFILE_PIC_FOLDER

reset_tokens = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_logged_user():
    user = None
    if session.get('user_id'):
        user = users_collection.find_one({'username': session['user_id']})
    return user

@app.context_processor
def inject_user_profile_pic():
    user = get_logged_user()
    notif_count = 0
    if user:
        notif_count = db['notifications'].count_documents({'to_user': user['username'], 'read': False})
    return {'logged_user': user, 'notif_count': notif_count}

@app.route('/')
def index():
    page = int(request.args.get('page', 1))
    # Filmes populares
    url_popular = f'https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&language=pt-BR&page={page}'
    response_popular = requests.get(url_popular)
    data_popular = response_popular.json()
    popular_movies = data_popular.get('results', [])[:8]
    total_pages = data_popular.get('total_pages', 1)

    # Lançamentos
    url_latest = f'https://api.themoviedb.org/3/movie/now_playing?api_key={TMDB_API_KEY}&language=pt-BR&page=1'
    response_latest = requests.get(url_latest)
    data_latest = response_latest.json()
    latest_movies = data_latest.get('results', [])[:8]

    # Recomendados (usando top rated como exemplo)
    url_recommended = f'https://api.themoviedb.org/3/movie/top_rated?api_key={TMDB_API_KEY}&language=pt-BR&page=1'
    response_recommended = requests.get(url_recommended)
    data_recommended = response_recommended.json()
    recommended_movies = data_recommended.get('results', [])[:8]

    # Gêneros
    url_genres = f'https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=pt-BR'
    response_genres = requests.get(url_genres)
    genres = response_genres.json().get('genres', [])

    # Filme em destaque (primeiro dos populares)
    featured_movie = None
    if popular_movies:
        featured_movie = popular_movies[0]
        # Buscar trailer do filme em destaque
        url_trailer = f"https://api.themoviedb.org/3/movie/{featured_movie['id']}/videos?api_key={TMDB_API_KEY}&language=pt-BR"
        response_trailer = requests.get(url_trailer)
        videos = response_trailer.json().get('results', [])
        trailer_url = None
        for video in videos:
            if video['site'] == 'YouTube' and video['type'] == 'Trailer':
                trailer_url = f"https://www.youtube.com/embed/{video['key']}"
                break
        featured_movie['trailer_url'] = trailer_url

    return render_template(
        'index.html',
        movies=popular_movies,  # compatibilidade com busca
        page=page,
        total_pages=total_pages,
        featured_movie=featured_movie,
        popular_movies=popular_movies,
        latest_movies=latest_movies,
        recommended_movies=recommended_movies,
        genres=genres
    )

@app.route('/search')
def search():
    query = request.args.get('q')
    genre = request.args.get('genre')
    year = request.args.get('year')
    min_vote = request.args.get('min_vote')
    country = request.args.get('country')
    language = request.args.get('language')
    min_duration = request.args.get('min_duration')
    max_duration = request.args.get('max_duration')
    certification = request.args.get('certification')
    page = int(request.args.get('page', 1))
    url = f'https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&language=pt-BR&query={query or ""}&page={page}'
    url += f'&with_original_language={language}'
    response = requests.get(url)
    data = response.json()
    movies = data.get('results', [])
    # Filtros adicionais
    if genre:
        movies = [m for m in movies if int(genre) in m.get('genre_ids', [])]
    if year:
        movies = [m for m in movies if str(m.get('release_date', '')).startswith(str(year))]
    if min_vote:
        try:
            min_vote = float(min_vote)
            movies = [m for m in movies if m.get('vote_average', 0) >= min_vote]
        except:
            pass
    if country:
        movies = [m for m in movies if country.lower() in (m.get('origin_country', []) or [''])[0].lower()]
    if min_duration:
        try:
            min_duration = int(min_duration)
            movies = [m for m in movies if m.get('runtime') and m['runtime'] >= min_duration]
        except:
            pass
    if max_duration:
        try:
            max_duration = int(max_duration)
            movies = [m for m in movies if m.get('runtime') and m['runtime'] <= max_duration]
        except:
            pass
    if certification:
        movies = [m for m in movies if m.get('certification') == certification]
    movies = movies[:8]
    total_pages = data.get('total_pages', 1)
    # Gêneros para o filtro
    url_genres = f'https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=pt-BR'
    response_genres = requests.get(url_genres)
    genres = response_genres.json().get('genres', [])
    return render_template('index.html', movies=movies, query=query, page=page, total_pages=total_pages, genres=genres)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        display_name = request.form['display_name']
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        # Confirmação de senha
        if password != confirm_password:
            return render_template('register.html', error='As senhas não coincidem!')
        # E-mail já existe
        if users_collection.find_one({'email': email}):
            return render_template('register.html', error='E-mail já cadastrado!')
        # Usuário já existe
        if users_collection.find_one({'username': username}):
            return render_template('register.html', error='Usuário já existe!')
        # Foto de perfil
        profile_pic = request.files.get('profile_pic')
        profile_pic_url = None
        if profile_pic and allowed_file(profile_pic.filename):
            ext = profile_pic.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            filepath = os.path.join(PROFILE_PIC_FOLDER, secure_filename(filename))
            img = Image.open(profile_pic)
            img = img.convert('RGB')
            img.thumbnail((256, 256))
            img.save(filepath)
            profile_pic_url = filepath.replace('static/', '/static/')
        # Gera id único
        user_id = str(uuid.uuid4())
        hashed_password = generate_password_hash(password)
        users_collection.insert_one({
            'user_id': user_id,
            'display_name': display_name,
            'email': email,
            'username': username,
            'password': hashed_password,
            'profile_pic': profile_pic_url
        })
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = users_collection.find_one({'username': username})
        if user and check_password_hash(user['password'], password):
            session['user_id'] = username
            return redirect(url_for('index'))
        return render_template('login.html', error='Invalid credentials!')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# Função para atualizar badges do usuário
BADGE_CONFIG = [
    {'key': 'commenter', 'label': 'Comentarista', 'levels': [5, 10, 20]},
    {'key': 'favoriter', 'label': 'Favoritador', 'levels': [5, 10, 20]},
]

def update_user_badges(user):
    badges = user.get('badges', {})
    # Comentários
    comment_count = db['comments'].count_documents({'user': user['username']})
    for lvl in BADGE_CONFIG[0]['levels']:
        if comment_count >= lvl:
            badges[f'commenter_{lvl}'] = True
    # Favoritos
    fav_count = len(user.get('favorites', []))
    for lvl in BADGE_CONFIG[1]['levels']:
        if fav_count >= lvl:
            badges[f'favoriter_{lvl}'] = True
    users_collection.update_one({'username': user['username']}, {'$set': {'badges': badges}})
    return badges

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/favorite/<int:movie_id>', methods=['POST'])
@login_required
def toggle_favorite(movie_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    user = users_collection.find_one({'username': session['user_id']})
    if not user:
        return redirect(url_for('login'))
    favorites = user.get('favorites', [])
    if movie_id in favorites:
        favorites.remove(movie_id)
    else:
        favorites.append(movie_id)
    users_collection.update_one({'username': user['username']}, {'$set': {'favorites': favorites}})
    # Atualiza badges
    user['favorites'] = favorites
    update_user_badges(user)
    return redirect(url_for('movie_detail', movie_id=movie_id))

# Notificações: coleção no banco
notifications_collection = db['notifications']

@app.route('/notifications')
@login_required
def notifications():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    notifs = list(notifications_collection.find({
        'to_user': session['user_id'],
        'read': False
    }))
    return render_template('notifications.html', notifications=notifs)

@app.route('/notifications/read/<notif_id>', methods=['POST'])
@login_required
def read_notification(notif_id):
    if not session.get('user_id'):
        return '', 401
    notifications_collection.update_one({'_id': notif_id, 'to_user': session['user_id']}, {'$set': {'read': True}})
    return redirect(url_for('notifications'))

@app.route('/movie/<int:movie_id>', methods=['GET', 'POST'])
def movie_detail(movie_id):
    url = f'https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=pt-BR&append_to_response=credits,videos,releases'
    response = requests.get(url)
    movie = response.json()
    # Trailer
    trailer_url = None
    for video in movie.get('videos', {}).get('results', []):
        if video['site'] == 'YouTube' and video['type'] == 'Trailer':
            trailer_url = f"https://www.youtube.com/embed/{video['key']}"
            break
    # Elenco
    cast = movie.get('credits', {}).get('cast', [])
    # Classificação indicativa
    certification = None
    for rel in movie.get('releases', {}).get('countries', []):
        if rel['iso_3166_1'] == 'BR':
            certification = rel.get('certification')
            break

    # Persistência de comentários
    comments_collection = db['comments']
    if request.method == 'POST' and session.get('user_id'):
        rating = int(request.form['rating'])
        text = request.form['text']
        user = users_collection.find_one({'username': session['user_id']})
        comment = {
            'movie_id': movie_id,
            'user': user['username'],
            'user_display_name': user.get('display_name', user['username']),
            'profile_pic': user.get('profile_pic'),
            'rating': rating,
            'text': text
        }
        comments_collection.insert_one(comment)
        # Atualiza badges
        update_user_badges(user)
        # Notificação para favoritos
        favorited_users = users_collection.find({'favorites': movie_id, 'username': {'$ne': user['username']}})
        for fav_user in favorited_users:
            notifications_collection.insert_one({
                'to_user': fav_user['username'],
                'movie_id': movie_id,
                'movie_title': movie.get('title'),
                'from_user': user['username'],
                'from_display_name': user.get('display_name', user['username']),
                'type': 'new_comment',
                'read': False
            })

    # Buscar todos os comentários desse filme
    comments = list(comments_collection.find({'movie_id': movie_id}))
    # Cálculo da avaliação média
    avg_rating = None
    rating_distribution = [0]*11  # 0 a 10
    if comments:
        ratings = [c.get('rating', 0) for c in comments if c.get('rating')]
        if ratings:
            avg_rating = round(sum(ratings) / len(ratings), 1)
            for r in ratings:
                if 0 <= r <= 10:
                    rating_distribution[r] += 1
    # Recomendações baseadas nos favoritos/listas do usuário
    recommendations = []
    if session.get('user_id'):
        user = users_collection.find_one({'username': session['user_id']})
        movie_ids = set(user.get('favorites', []))
        for lst in user.get('lists', {}).values():
            movie_ids.update(lst)
        movie_ids.discard(int(movie_id))
        genre_ids = set()
        for mid in movie_ids:
            m = requests.get(f'https://api.themoviedb.org/3/movie/{mid}?api_key={TMDB_API_KEY}&language=pt-BR').json()
            for g in m.get('genres', []):
                genre_ids.add(g['id'])
        # Busca filmes recomendados por gênero
        for gid in list(genre_ids)[:3]:
            rec_url = f'https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&language=pt-BR&with_genres={gid}&sort_by=popularity.desc'
            rec_resp = requests.get(rec_url)
            recs = rec_resp.json().get('results', [])
            for rec in recs:
                if rec['id'] != int(movie_id) and rec['id'] not in movie_ids:
                    recommendations.append(rec)
            if len(recommendations) >= 8:
                break
        recommendations = recommendations[:8]
    is_favorite = False
    if session.get('user_id'):
        user = users_collection.find_one({'username': session['user_id']})
        if user and 'favorites' in user:
            is_favorite = movie_id in user['favorites']

    return render_template(
        'movie_detail.html',
        movie=movie,
        cast=cast,
        trailer_url=trailer_url,
        certification=certification,
        comments=comments,
        avg_rating=avg_rating,
        rating_distribution=rating_distribution,
        recommendations=recommendations,
        is_favorite=is_favorite
    )

@app.route('/producers')
def producers():
    # Busca lista de produtoras populares (mock ou via TMDB)
    # TMDB não tem endpoint direto para produtoras populares, então exemplo com algumas conhecidas
    producers = [
        {'id': 2, 'name': 'Walt Disney Pictures'},
        {'id': 3, 'name': 'Pixar Animation Studios'},
        {'id': 420, 'name': 'Marvel Studios'},
        {'id': 6125, 'name': 'Lucasfilm Ltd.'},
        {'id': 4, 'name': 'Warner Bros.'},
        {'id': 5, 'name': 'Columbia Pictures'},
        {'id': 33, 'name': 'Universal Pictures'},
        {'id': 21, 'name': 'Metro-Goldwyn-Mayer'},
    ]
    return render_template('producers.html', producers=producers)

@app.route('/producer/<int:producer_id>')
def producer_movies(producer_id):
    year = request.args.get('year')
    genre = request.args.get('genre')
    page = int(request.args.get('page', 1))
    url = f'https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&language=pt-BR&with_companies={producer_id}&page={page}'
    if year:
        url += f'&primary_release_year={year}'
    if genre:
        url += f'&with_genres={genre}'
    response = requests.get(url)
    data = response.json()
    movies = data.get('results', [])
    total_pages = data.get('total_pages', 1)
    # Gêneros para o filtro
    url_genres = f'https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=pt-BR'
    response_genres = requests.get(url_genres)
    genres = response_genres.json().get('genres', [])
    # Nome da produtora
    producer_name = None
    if movies and movies[0].get('production_companies'):
        for company in movies[0]['production_companies']:
            if company['id'] == producer_id:
                producer_name = company['name']
                break
    return render_template('producer_movies.html', movies=movies, genres=genres, producer_id=producer_id, producer_name=producer_name, year=year, genre=genre, page=page, total_pages=total_pages)

@app.route('/login/google')
def login_google():
    # Exibe mensagem em breve dentro do template de login
    return render_template('login.html', google_soon=True)

@app.route('/api')
def api_docs():
    return {
        "endpoints": [
            {"url": "/api/movies", "desc": "Lista de filmes populares"},
            {"url": "/api/movie/<id>", "desc": "Detalhes de um filme por ID"}
        ],
        "exemplo_lista": "/api/movies",
        "exemplo_detalhe": "/api/movie/603"
    }

@app.route('/api/movies')
def api_movies():
    url = f'https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&language=pt-BR&page=1'
    response = requests.get(url)
    data = response.json()
    return {"results": data.get('results', [])}

@app.route('/api/movie/<int:movie_id>')
def api_movie_detail(movie_id):
    url = f'https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=pt-BR&append_to_response=credits,videos,releases'
    response = requests.get(url)
    data = response.json()
    return data

@app.route('/api/notifications')
@login_required
def api_notifications():
    user = users_collection.find_one({'username': session['user_id']})
    notifications = list(db['notifications'].find({'to_user': user['username'], 'read': False}))
    for n in notifications:
        n['_id'] = str(n['_id'])
    return {'notifications': notifications, 'count': len(notifications)}

@app.route('/ranking')
def ranking():
    # Conta comentários por usuário
    comments_collection = db['comments']
    pipeline = [
        {"$group": {"_id": "$user", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20}
    ]
    ranking_data = list(comments_collection.aggregate(pipeline))
    # Busca dados do usuário
    users = {u['username']: u for u in users_collection.find({"username": {"$in": [r['_id'] for r in ranking_data]}})}
    for r in ranking_data:
        user = users.get(r['_id'])
        r['display_name'] = user.get('display_name', r['_id']) if user else r['_id']
        r['profile_pic'] = user.get('profile_pic') if user else None
        r['badges'] = user.get('badges', {}) if user else {}
    return render_template('ranking.html', ranking=ranking_data)

@app.route('/profile')
@login_required
def profile():
    user = users_collection.find_one({'username': session['user_id']})
    # Busca detalhes dos filmes favoritos
    favorites = []
    if user and user.get('favorites'):
        for movie_id in user['favorites']:
            url = f'https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=pt-BR'
            resp = requests.get(url)
            if resp.status_code == 200:
                favorites.append(resp.json())
    # Busca histórico de comentários do usuário
    comments_collection = db['comments']
    user_comments = list(comments_collection.find({'user': user['username']}))
    # Adiciona título do filme a cada comentário
    for c in user_comments:
        movie_id = c.get('movie_id')
        if movie_id:
            url = f'https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=pt-BR'
            resp = requests.get(url)
            if resp.status_code == 200:
                c['movie_title'] = resp.json().get('title', 'Filme')
            else:
                c['movie_title'] = 'Filme'
        else:
            c['movie_title'] = 'Filme'
    return render_template('profile.html', user=user, favorites=favorites, user_comments=user_comments)

@app.route('/lists', methods=['GET', 'POST'])
@login_required
def lists():
    user = users_collection.find_one({'username': session['user_id']})
    if request.method == 'POST':
        list_name = request.form.get('list_name')
        if list_name:
            lists = user.get('lists', {})
            if list_name not in lists:
                lists[list_name] = []
                users_collection.update_one({'username': user['username']}, {'$set': {'lists': lists}})
    user = users_collection.find_one({'username': session['user_id']})
    return render_template('lists.html', user=user)

@app.route('/lists/add/<int:movie_id>', methods=['POST'])
@login_required
def add_to_list(movie_id):
    list_name = request.form.get('list_name')
    user = users_collection.find_one({'username': session['user_id']})
    lists = user.get('lists', {})
    if list_name and movie_id not in lists.get(list_name, []):
        lists.setdefault(list_name, []).append(movie_id)
        users_collection.update_one({'username': user['username']}, {'$set': {'lists': lists}})
    return redirect(url_for('lists'))

@app.route('/lists/remove/<int:movie_id>', methods=['POST'])
@login_required
def remove_from_list(movie_id):
    list_name = request.form.get('list_name')
    user = users_collection.find_one({'username': session['user_id']})
    lists = user.get('lists', {})
    if list_name and movie_id in lists.get(list_name, []):
        lists[list_name].remove(movie_id)
        users_collection.update_one({'username': user['username']}, {'$set': {'lists': lists}})
    return redirect(url_for('lists'))

@app.route('/profile/edit', methods=['POST'])
@login_required
def edit_profile():
    user = users_collection.find_one({'username': session['user_id']})
    display_name = request.form.get('display_name', user['display_name'])
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    profile_pic = request.files.get('profile_pic')
    update_fields = {'display_name': display_name}
    # Atualiza senha se fornecida e confirmada
    if new_password:
        if new_password == confirm_password:
            update_fields['password'] = generate_password_hash(new_password)
        else:
            return redirect(url_for('profile', error='As senhas não coincidem.'))
    # Atualiza foto de perfil se fornecida
    if profile_pic and allowed_file(profile_pic.filename):
        ext = profile_pic.filename.rsplit('.', 1)[1].lower()
        filename = f"{user['username']}_profile.{ext}"
        filepath = os.path.join(PROFILE_PIC_FOLDER, secure_filename(filename))
        img = Image.open(profile_pic)
        img = img.convert('RGB')
        img.thumbnail((256, 256))
        img.save(filepath)
        profile_pic_url = filepath.replace('static/', '/static/')
        update_fields['profile_pic'] = profile_pic_url
    users_collection.update_one({'username': user['username']}, {'$set': update_fields})
    return redirect(url_for('profile'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = users_collection.find_one({'email': email})
        if not user:
            return render_template('forgot_password.html', error='E-mail não encontrado.')
        # Gera token seguro
        token = secrets.token_urlsafe(32)
        reset_tokens[token] = {'username': user['username'], 'expires': datetime.utcnow() + timedelta(hours=1)}
        # Monta link
        reset_link = url_for('reset_password', token=token, _external=True)
        # Envia e-mail
        subject = 'Redefinição de senha - CineBook'
        body = f'Olá,\n\nClique no link para redefinir sua senha: {reset_link}\n\nSe não solicitou, ignore este e-mail.'
        send_email(email, subject, body)
        return render_template('forgot_password.html', message='E-mail enviado! Verifique sua caixa de entrada.')
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    data = reset_tokens.get(token)
    if not data or data['expires'] < datetime.utcnow():
        return render_template('reset_password.html', error='Token inválido ou expirado.')
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        if new_password != confirm_password:
            return render_template('reset_password.html', error='As senhas não coincidem.')
        users_collection.update_one({'username': data['username']}, {'$set': {'password': generate_password_hash(new_password)}})
        del reset_tokens[token]
        return render_template('reset_password.html', message='Senha redefinida com sucesso!')
    return render_template('reset_password.html')

def send_email(to, subject, body):
    # Configuração do servidor SMTP (exemplo Gmail)
    smtp_server = os.getenv('SMTP_SERVER')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to, msg.as_string())
    except Exception as e:
        print('Erro ao enviar e-mail:', e)

if __name__ == '__main__':
    app.run(debug=True)
