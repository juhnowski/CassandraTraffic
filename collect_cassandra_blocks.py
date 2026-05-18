import os
import shutil
import time
import subprocess
from cassandra.cluster import Cluster

OUTPUT_DIR = "./cassandra_bench_blocks"
CASS_DATA_DIR = "./cassandra_data/data/bench_ks" # Путь к данным нашего Keyspace

SCENARIOS = {
    "1_duplicates": {
        "table": "test_duplicates",
        "schema": """
            CREATE TABLE test_duplicates (
                id int PRIMARY KEY,
                payload text
            ) WITH compression = {'enabled': 'false'};
        """,
        "insert": "INSERT INTO test_duplicates (id, payload) VALUES (%s, %s);",
        "data_gen": lambda: [
            (i, "КОНСТАНТНЫЙ_ТЕКСТ_ДЛЯ_ПРОВЕРКИ_ДЕДУПЛИКАЦИИ_ВАРИАНТ_Ц_Ц_Ц_Ц_Ц_Ц" if i % 2 == 0 
                     else "ДРУГОЙ_ШАБЛОННЫЙ_БЛОК_ДАННЫХ_МИН_МАКС_Ц_Ц_Ц_Ц_Ц_Ц_Ц_Ц_Ц")
            for i in range(30000)
        ]
    },
    "2_denormalized": {
        "table": "test_denormalized",
        "schema": """
            CREATE TABLE test_denormalized (
                id int PRIMARY KEY,
                region text,
                manager text,
                status text
            ) WITH compression = {'enabled': 'false'};
        """,
        "insert": "INSERT INTO test_denormalized (id, region, manager, status) VALUES (%s, %s, %s, %s);",
        "data_gen": lambda: [
            (i, ["Москва", "СПб", "Сибирь"][i % 3], ["Иванов", "Петров"][i % 2], "COMPLETED")
            for i in range(25000)
        ]
    },
    "3_binary": {
        "table": "test_binary",
        "schema": """
            CREATE TABLE test_binary (
                id int PRIMARY KEY,
                raw_bytes blob
            ) WITH compression = {'enabled': 'false'};
        """,
        "insert": "INSERT INTO test_binary (id, raw_bytes) VALUES (%s, %s);",
        "data_gen": lambda: [(i, os.urandom(4000)) for i in range(1000)]
    }
}

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Подключаемся к локальной Cassandra
    cluster = Cluster(['127.0.0.1'], port=9042)
    session = cluster.connect()
    
    # Создаем Keyspace (базу данных)
    session.execute("""
        CREATE KEYSPACE IF NOT EXISTS bench_ks 
        WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
    """)
    session.set_keyspace('bench_ks')
    
    table_uuid_paths = {} # Словарь для фиксации внутренних ID таблиц
    
    for name, config in SCENARIOS.items():
        print(f"\n--- Сценарий Cassandra: {name} ---")
        table_name = config["table"]
        
        session.execute(f"DROP TABLE IF EXISTS {table_name};")
        session.execute(config["schema"])
        
        print(f"    Массовая вставка строк (CQL)...")
        prepared = session.prepare(config["insert"])
        rows = config["data_gen"]()
        
        # Вставляем данные пакетами или поштучно (для теста достаточно поштучно)
        for row in rows:
            session.execute(prepared, row)
            
    cluster.shutdown()
    
    # Принудительно сбрасываем Memtables на диск с помощью nodetool
    print("\n[+] Вызов 'nodetool flush' для создания SSTables на диске...")
    subprocess.run("nodetool flush bench_ks", shell=True)
    time.sleep(3) # Даем время файловой системе завершить запись
    
    print("\n[+] Сбор сырых бинарных файлов Data.db...")
    # Ищем файлы в директории данных. Cassandra создает папки вида: table_name-uuid/
    for name, config in SCENARIOS.items():
        table_name = config["table"]
        table_dir = os.path.join(CASS_DATA_DIR)
        
        # Находим нужную подпапку таблицы (с суффиксом UUID)
        subdirs = [d for d in os.listdir(table_dir) if d.startswith(table_name + "-")]
        if not subdirs:
            print(f"    Ошибка: папка для таблицы {table_name} не найдена!")
            continue
            
        target_dir = os.path.join(table_dir, subdirs[0])
        
        # Находим файл данных с суффиксом Data.db (например, na-1-big-Data.db)
        data_files = [f for f in os.listdir(target_dir) if f.endswith("-Data.db")]
        if not data_files:
            print(f"    Ошибка: SSTable файл Data.db для {table_name} не найден!")
            continue
            
        # Берем самый свежий/крупный файл данных
        src_file = os.path.join(target_dir, sorted(data_files)[-1])
        dest_file = os.path.join(OUTPUT_DIR, f"cassandra_{name}_Data.db.raw")
        
        shutil.copy(src_file, dest_file)
        size_kb = os.path.getsize(dest_file) // 1024
        print(f"    Сохранено: {dest_file} ({size_kb} KB)")
        
    print("\n[+] Сбор блоков для Cassandra завершен успешно!")

if __name__ == "__main__":
    main()
