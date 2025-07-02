import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv('MONGODB_URI')

try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000, tls=True, tlsAllowInvalidCertificates=True)
    print('Conectando ao MongoDB...')
    print('Databases disponíveis:', client.list_database_names())
    print('Conexão bem-sucedida!')
except Exception as e:
    print('Erro ao conectar ao MongoDB:')
    print(e)
