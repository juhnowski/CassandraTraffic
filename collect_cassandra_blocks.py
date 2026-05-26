import os
import sys
import shutil
import time
import socket
import subprocess
from cassandra.cluster import Cluster

# Пути стенда внутри директории проекта
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CASS_DIR = os.path.join(BASE_DIR, "cassandra_data")
CASS_CONF = os.path.join(CASS_DIR, "conf")
OUTPUT_DIR = os.path.join(BASE_DIR, "cassandra_bench_blocks")
CASS_DATA_DIR = os.path.join(CASS_DIR, "data", "bench_ks")

SCENARIOS = {
    "1_duplicates": {
        "table": "test_duplicates",
        "schema": "CREATE TABLE test_duplicates (id int PRIMARY KEY, payload text) WITH compression = {'enabled': 'false'};",
        "insert": "INSERT INTO test_duplicates (id, payload) VALUES (?, ?);",
        "data_gen": lambda: [
            (i, "КОНСТАНТНЫЙ_ТЕКСТ_ДЛЯ_ПРОВЕРКИ_ДЕДУПЛИКАЦИИ_ВАРИАНТ_Ц_Ц_Ц_Ц_Ц_Ц" if i % 2 == 0 
                     else "ДРУГОЙ_ШАБЛОННЫЙ_БЛОК_ДАННЫХ_МИН_МАКС_Ц_Ц_Ц_Ц_Ц_Ц_Ц_Ц_Ц")
            for i in range(30000)
        ]
    },
    "2_denormalized": {
        "table": "test_denormalized",
        "schema": "CREATE TABLE test_denormalized (id int PRIMARY KEY, region text, manager text, status text) WITH compression = {'enabled': 'false'};",
        "insert": "INSERT INTO test_denormalized (id, region, manager, status) VALUES (?, ?, ?, ?);",
        "data_gen": lambda: [
            (i, ["Москва", "СПб", "Сибирь"][i % 3], ["Иванов", "Петров"][i % 2], "COMPLETED")
            for i in range(25000)
        ]
    },
    "3_binary": {
        "table": "test_binary",
        "schema": "CREATE TABLE test_binary (id int PRIMARY KEY, raw_bytes blob) WITH compression = {'enabled': 'false'};",
        "insert": "INSERT INTO test_binary (id, raw_bytes) VALUES (?, ?);",
        "data_gen": lambda: [(i, os.urandom(4000)) for i in range(1000)]
    }
}

def setup_configs():
    """Генерирует файлы настроек под абсолютный путь проекта"""
    for p in [CASS_CONF, os.path.join(CASS_DIR, "data"), os.path.join(CASS_DIR, "commitlog"), 
              os.path.join(CASS_DIR, "saved_caches"), os.path.join(CASS_DIR, "hints"), os.path.join(CASS_DIR, "logs"), OUTPUT_DIR]:
        os.makedirs(p, exist_ok=True)

    with open(os.path.join(CASS_CONF, "cassandra.yaml"), "w") as f:
        f.write(f"""
cluster_name: 'TestCluster'
num_tokens: 16
authenticator: AllowAllAuthenticator
authorizer: AllowAllAuthorizer
partitioner: org.apache.cassandra.dht.Murmur3Partitioner
data_file_directories:
    - {CASS_DIR}/data
commitlog_directory: {CASS_DIR}/commitlog
saved_caches_directory: {CASS_DIR}/saved_caches
hints_directory: {CASS_DIR}/hints
commitlog_sync: periodic
commitlog_sync_period_in_ms: 10000
native_transport_port: 9042
listen_address: 127.0.0.1
rpc_address: 127.0.0.1
endpoint_snitch: SimpleSnitch
storage_port: 7000
ssl_storage_port: 7001
start_native_transport: true
column_index_size_in_kb: 64
seed_provider:
    - class_name: org.apache.cassandra.locator.SimpleSeedProvider
      parameters:
          - seeds: "127.0.0.1"
""")

    with open(os.path.join(CASS_CONF, "logback.xml"), "w") as f:
        f.write(f"""
<configuration scan="true" scanPeriod="60 seconds">
  <appender name="FILE" class="ch.qos.logback.core.FileAppender">
    <file>{CASS_DIR}/logs/system.log</file>
    <encoder><pattern>%-5level [%thread] %date{{ISO8601}} %F:%L - %msg%n</pattern></encoder>
  </appender>
  <root level="INFO"><appender-ref ref="FILE" /></root>
</configuration>
""")

def find_cassandra_libs():
    """Автоматически находит JAR-библиотеки Cassandra в Nix Store"""
    cass_bin = shutil.which("cassandra")
    if not cass_bin:
        print("[!] Ошибка: Утилита cassandra не найдена в PATH. Вы вошли в nix develop?")
        sys.exit(1)
    
    real_bin = os.path.realpath(cass_bin)
    cass_base = os.path.abspath(os.path.join(real_bin, "..", ".."))
    
    lib_dir = os.path.join(cass_base, "share", "cassandra", "lib")
    conf_dir = os.path.join(cass_base, "share", "cassandra", "conf")
    
    if not os.path.exists(lib_dir):
        lib_dir = os.path.join(cass_base, "lib")
        conf_dir = os.path.join(cass_base, "conf")

    return conf_dir, lib_dir

def wait_for_port(port=9042, timeout=60):
    """Ожидает доступности нативного端口а Cassandra"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (socket.timeout, ConnectionRefusedError):
            time.sleep(1)
    return False

def main():
    setup_configs()
    store_conf, store_lib = find_cassandra_libs()
    
    jamm_agent = None
    for f in os.listdir(store_lib):
        if f.startswith("jamm-") and f.endswith(".jar"):
            jamm_agent = os.path.join(store_lib, f)
            break
            
    if not jamm_agent:
        print("[!] Ошибка: Не удалось найти java-агент jamm.jar!")
        sys.exit(1)
        
    classpath = f"{CASS_CONF}:{store_conf}:{store_lib}/*"
    
    java_cmd = [
        "java", "-Xmx1G", "-Xms1G",
        "-Djava.security.manager=allow",
        f"-javaagent:{jamm_agent}",
        "-Dcom.sun.management.jmxremote.port=7199",
        "-Dcom.sun.management.jmxremote.authenticate=false",
        "-Dcom.sun.management.jmxremote.ssl=false",
        "-Dcassandra.config=file:///" + os.path.join(CASS_CONF, "cassandra.yaml"),
        "-Dcassandra.logback.configurationFile=" + os.path.join(CASS_CONF, "logback.xml"),
        "-Dcassandra.logdir=" + os.path.join(CASS_DIR, "logs"),
        "-Dcassandra-foreground=false",
        
        "--add-exports=java.base/sun.nio.ch=ALL-UNNAMED",
        "--add-exports=java.base/jdk.internal.ref=ALL-UNNAMED",
        "--add-exports=java.base/jdk.internal.misc=ALL-UNNAMED",
        "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED",
        "--add-opens=java.base/jdk.internal.ref=ALL-UNNAMED",
        "--add-opens=java.base/java.lang=ALL-UNNAMED",
        "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
        "--add-opens=java.base/java.util=ALL-UNNAMED",
        "--add-opens=java.base/java.util.concurrent=ALL-UNNAMED",
        "--add-opens=java.base/java.util.concurrent.atomic=ALL-UNNAMED",
        "--add-opens=java.base/sun.misc=ALL-UNNAMED",
        "--add-opens=java.base/java.nio=ALL-UNNAMED",
        "--add-opens=java.base/java.io=ALL-UNNAMED",
        
        "-cp", classpath,
        "org.apache.cassandra.service.CassandraDaemon"
    ]
    
    print("[+] Запуск изолированного процесса Cassandra с Java-агентом...")
    proc = subprocess.Popen(java_cmd, stdout=subprocess.DEVNULL, stderr=sys.stderr)
    
    try:
        print("    Ожидание инициализации БД (порт 9042)...")
        if not wait_for_port():
            print("[!] Ошибка: Не удалось дождаться запуска Cassandra. Проверьте логи в cassandra_data/logs/system.log")
            return
        
        print("[+] Соединение установлено. Начинаем выполнение сценариев...")
        cluster = Cluster(['127.0.0.1'], port=9042)
        session = cluster.connect()
        
        session.execute("""
            CREATE KEYSPACE IF NOT EXISTS bench_ks 
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
        """)
        session.set_keyspace('bench_ks')
        
        for name, config in SCENARIOS.items():
            print(f"\n--- Сценарий Cassandra: {name} ---")
            table_name = config["table"]
            
            session.execute(f"DROP TABLE IF EXISTS {table_name};")
            session.execute(config["schema"])
            
            print(f"    Массовая вставка строк (CQL)...")
            prepared = session.prepare(config["insert"])
            rows = config["data_gen"]()
            
            for row in rows:
                session.execute(prepared, row)
                
        cluster.shutdown()
        
        print("\n[+] Вызов 'nodetool flush' для создания SSTables на диске...")
        nodetool_env = os.environ.copy()
        nodetool_env["CASSANDRA_CONF"] = CASS_CONF
        nodetool_env["JVM_OPTS"] = (
            "--add-exports=java.base/sun.nio.ch=ALL-UNNAMED "
            "--add-exports=java.base/jdk.internal.ref=ALL-UNNAMED "
            "--add-opens=java.base/jdk.internal.ref=ALL-UNNAMED "
            "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED "
            "--add-opens=java.base/java.lang=ALL-UNNAMED "
            "--add-opens=java.base/java.nio=ALL-UNNAMED"
        )
        subprocess.run(f"nodetool -h 127.0.0.1 -p 7199 flush bench_ks", shell=True, env=nodetool_env)
        time.sleep(15)
        
        print("\n[+] Сбор сырых бинарных файлов Data.db...")
        if not os.path.exists(CASS_DATA_DIR):
            print(f"    Ошибка: Базовая папка данных {CASS_DATA_DIR} не существует!")
            return

        for name, config in SCENARIOS.items():
            table_name = config["table"]
            # Находим нужную подпапку таблицы (с суффиксом UUID)
            subdirs = [d for d in os.listdir(CASS_DATA_DIR) if d.startswith(table_name + "-")]
            if not subdirs:
                print(f"    Ошибка: папка для таблицы {table_name} не найдена!")
                continue
                
            # ФИКС: Берем первый элемент списка [0]
            target_dir = os.path.join(CASS_DATA_DIR, subdirs[0])
            data_files = [f for f in os.listdir(target_dir) if "Data.db" in f]
            if not data_files:
                print(f"    Ошибка: SSTable файл Data.db для {table_name} не найден!")
                continue
                
            src_file = os.path.join(target_dir, sorted(data_files)[-1])
            dest_file = os.path.join(OUTPUT_DIR, f"cassandra_{name}_Data.db.raw")
            
            shutil.copy(src_file, dest_file)
            size_kb = os.path.getsize(dest_file) // 1024
            print(f"    Сохранено: {dest_file} ({size_kb} KB)")

            
        print("\n[+] Сбор блоков для Cassandra завершен успешно!")

    finally:
        print("[+] Остановка локального процесса Cassandra...")
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()
