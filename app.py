from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
import requests
import unicodedata
import re
from functools import lru_cache

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Database Configuration
def get_db_connection():
    conn = sqlite3.connect('livros.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS livros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            autor TEXT,
            generos TEXT,
            paginas INTEGER,
            sinopse TEXT,
            anotacoes TEXT,
            data_adicao TEXT,
            capa TEXT
        )
    ''')
    
    # Check and add capa column if it doesn't exist
    cursor = conn.execute("PRAGMA table_info(livros)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'capa' not in columns:
        conn.execute('ALTER TABLE livros ADD COLUMN capa TEXT')
    
    conn.commit()
    conn.close()

init_db()

def normalizar_texto(texto):
    if not texto:
        return ""
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII')
    texto = texto.lower()
    texto = re.sub(r'[^\w\s]', '', texto)
    return texto.strip()

@lru_cache(maxsize=100)
def buscar_openlibrary(titulo):
    try:
        titulo_busca = normalizar_texto(titulo)
        search_url = f'https://openlibrary.org/search.json?title={titulo_busca}&limit=1'
        search_response = requests.get(search_url, timeout=10)
        search_data = search_response.json()
        
        if not search_data.get('docs'):
            return {}
            
        book_data = search_data['docs'][0]
        
        cover_id = book_data.get('cover_edition_key', '') or book_data.get('cover_i', '')
        cover_url = None
        if cover_id:
            if isinstance(cover_id, int):
                cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
            else:
                cover_url = f"https://covers.openlibrary.org/b/olid/{cover_id}-M.jpg"
        
        description = ''
        work_key = book_data.get('key', '')
        if work_key:
            try:
                work_response = requests.get(f'https://openlibrary.org{work_key}.json', timeout=5)
                work_data = work_response.json()
                if work_data.get('description'):
                    if isinstance(work_data['description'], dict):
                        description = work_data['description'].get('value', '')
                    else:
                        description = work_data['description']
                elif work_data.get('excerpts'):
                    description = work_data['excerpts'][0]['text']
            except:
                pass
        
        generos = []
        if book_data.get('subject'):
            generos = [g.capitalize() for g in book_data['subject'][:3]]
        elif book_data.get('subject_keywords'):
            generos = [g.capitalize() for g in book_data['subject_keywords'][:3]]
        
        return {
            'titulo': book_data.get('title', titulo),
            'autor': ', '.join(book_data.get('author_name', [''])),
            'generos': ', '.join(generos) if generos else '',
            'paginas': book_data.get('number_of_pages_median', '') or book_data.get('number_of_pages', ''),
            'sinopse': description,
            'capa': cover_url
        }
    except requests.exceptions.RequestException:
        return {}

@lru_cache(maxsize=100)
def buscar_googlebooks(titulo):
    try:
        search_url = f'https://www.googleapis.com/books/v1/volumes?q=intitle:{titulo}&maxResults=1'
        search_response = requests.get(search_url, timeout=10)
        search_data = search_response.json()
        
        if not search_data.get('items'):
            return {}
            
        book_data = search_data['items'][0]['volumeInfo']
        
        cover_url = None
        if book_data.get('imageLinks'):
            cover_url = book_data['imageLinks'].get('thumbnail', '').replace('http://', 'https://')
        
        description = book_data.get('description', '')
        
        # Get genres from Google Books
        generos = []
        if book_data.get('categories'):
            generos = [g.capitalize() for g in book_data['categories'][:3]]
        
        return {
            'paginas': book_data.get('pageCount', ''),
            'sinopse': description,
            'capa': cover_url,
            'generos': ', '.join(generos) if generos else ''
        }
    except requests.exceptions.RequestException:
        return {}

@lru_cache(maxsize=100)
def buscar_livro_apis(titulo):
    try:
        dados_openlib = buscar_openlibrary(titulo)
        dados_google = buscar_googlebooks(titulo)
        
        # Combine data, prioritizing OpenLibrary
        dados_combinados = {
            'titulo': dados_openlib.get('titulo', titulo),
            'autor': dados_openlib.get('autor', ''),
            'generos': dados_openlib.get('generos', '') or dados_google.get('generos', ''),
            'paginas': dados_openlib.get('paginas', '') or dados_google.get('paginas', ''),
            'sinopse': dados_openlib.get('sinopse', '') or dados_google.get('sinopse', ''),
            'capa': dados_openlib.get('capa', '') or dados_google.get('capa', '')
        }
        
        return dados_combinados
    except Exception as e:
        app.logger.error(f"Erro ao buscar livro: {str(e)}")
        return None

@app.route('/')
def index():
    busca = request.args.get('busca', '')
    conn = get_db_connection()
    
    if busca:
        livros = conn.execute(
            'SELECT * FROM livros WHERE titulo LIKE ?',
            (f'%{busca}%',)
        ).fetchall()
    else:
        livros = conn.execute('SELECT * FROM livros ORDER BY id DESC').fetchall()
    
    conn.close()
    return render_template('index.html', livros=livros, busca=busca)

@app.route('/adicionar', methods=['GET', 'POST'])
def adicionar():
    if request.method == 'POST':
        titulo = request.form['titulo'].strip()
        autor = request.form.get('autor', '').strip()
        generos = request.form.get('generos', '').strip()
        paginas = request.form.get('paginas', '')
        sinopse = request.form.get('sinopse', '').strip()
        capa = request.form.get('capa', '').strip()

        if not titulo:
            flash('Título é obrigatório para salvar!', 'danger')
        else:
            conn = get_db_connection()
            conn.execute(
                '''INSERT INTO livros 
                (titulo, autor, generos, paginas, sinopse, anotacoes, data_adicao, capa)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (titulo, autor or None, generos or None, paginas or None, 
                 sinopse or None, '', datetime.now().strftime('%d/%m/%Y %H:%M'), capa or None)
            )
            conn.commit()
            conn.close()
            flash('Livro adicionado com sucesso!', 'success')
            return redirect(url_for('index'))
    
    return render_template('adicionar.html')

@app.route('/buscar-info', methods=['POST'])
def buscar_info():
    titulo = request.form['titulo'].strip()
    
    if not titulo:
        flash('Por favor, insira o título do livro', 'danger')
        return redirect(url_for('adicionar'))
    
    # Clear cache to force fresh search
    buscar_livro_apis.cache_clear()
    buscar_openlibrary.cache_clear()
    buscar_googlebooks.cache_clear()
    
    livro = buscar_livro_apis(titulo)
    
    if livro:
        livro['titulo'] = livro['titulo'] or titulo
        livro['autor'] = livro['autor'] or ''
        return render_template('adicionar.html', **livro)
    
    flash('Nenhuma informação encontrada para este livro. Preencha os campos manualmente.', 'warning')
    return render_template('adicionar.html', titulo=titulo)

@app.route('/detalhes/<int:id>', methods=['GET', 'POST'])
def detalhes(id):
    conn = get_db_connection()
    
    if request.method == 'POST':
        # Processar o salvamento das anotações
        anotacoes = request.form.get('anotacoes', '')
        conn.execute(
            'UPDATE livros SET anotacoes = ? WHERE id = ?',
            (anotacoes, id)
        )
        conn.commit()
        flash('Anotações salvas com sucesso!', 'success')
    
    livro = conn.execute('SELECT * FROM livros WHERE id = ?', (id,)).fetchone()
    conn.close()
    
    if not livro:
        flash('Livro não encontrado', 'danger')
        return redirect(url_for('index'))
    
    return render_template('detalhes.html', livro=livro)

@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar(id):
    conn = get_db_connection()
    
    if request.method == 'POST':
        titulo = request.form['titulo'].strip()
        autor = request.form.get('autor', '').strip()
        generos = request.form.get('generos', '').strip()
        paginas = request.form.get('paginas', '')
        sinopse = request.form.get('sinopse', '').strip()
        capa = request.form.get('capa', '').strip()

        conn.execute(
            '''UPDATE livros SET 
            titulo = ?, autor = ?, generos = ?, paginas = ?, sinopse = ?, capa = ?
            WHERE id = ?''',
            (titulo, autor or None, generos or None, paginas or None, sinopse or None, capa or None, id)
        )
        conn.commit()
        conn.close()
        flash('Livro atualizado com sucesso!', 'success')
        return redirect(url_for('detalhes', id=id))
    
    livro = conn.execute('SELECT * FROM livros WHERE id = ?', (id,)).fetchone()
    conn.close()
    
    if not livro:
        flash('Livro não encontrado', 'danger')
        return redirect(url_for('index'))
    
    return render_template('editar.html', livro=livro)

@app.route('/excluir/<int:id>')
def excluir(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM livros WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Livro excluído com sucesso', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)