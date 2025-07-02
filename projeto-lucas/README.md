# site-generico: Flask Movie Search App

This is a minimal Flask web app for searching movies (TMDB API) and user registration/login (MongoDB).

## Features
- Homepage with popular movies
- Search movies
- Register and login/logout

## Setup
1. Crie um arquivo `.env` com suas chaves:
   ```
   TMDB_API_KEY=your_tmdb_api_key
   MONGODB_URI=your_mongodb_uri
   SECRET_KEY=your_secret_key
   ```
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Execute o app:
   ```bash
   python app.py
   ```

## Estrutura
- `app.py`: Código principal Flask
- `templates/`: HTMLs
- `static/`: CSS
- `.env`: Variáveis de ambiente
- `requirements.txt`: Dependências
