{
  description = "Стенд для сбора сырых несжатых SSTables Apache Cassandra";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux"; # Замените на aarch64-linux / x86_64-darwin, если у вас другая платформа
      pkgs = import nixpkgs { inherit system; };
      
      pythonEnv = pkgs.python3.withPackages (ps: [
        ps.cassandra-driver # Официальный драйвер для работы с Cassandra
      ]);
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [
          pkgs.cassandra_4 # Используем стабильную 4-ю ветку Cassandra
          pkgs.jre8        # Cassandra 4 отлично работает на Java 8/11
          pythonEnv
        ];

        shellHook = ''
          export CASS_DIR="$PWD/cassandra_data"
          export CASS_CONF="$CASS_DIR/conf"
          export PORT=9042
          
          mkdir -p "$CASS_CONF" "$CASS_DIR/data" "$CASS_DIR/commitlog" "$CASS_DIR/saved_caches" "$CASS_DIR/hints" "$CASS_DIR/logs"

          # Генерируем локальный cassandra.yaml
          if [ ! -f "$CASS_CONF/cassandra.yaml" ]; then
            echo "[Nix] Создание локальной конфигурации Cassandra..."
            cat <<EOF > "$CASS_CONF/cassandra.yaml"
cluster_name: 'TestCluster'
num_tokens: 16
authenticator: AllowAllAuthenticator
authorizer: AllowAllAuthenticator
partitioner: org.apache.cassandra.dht.Murmur3Partitioner
data_file_directories:
    - $CASS_DIR/data
commitlog_directory: $CASS_DIR/commitlog
saved_caches_directory: $CASS_DIR/saved_caches
hints_directory: $CASS_DIR/hints
transport_port: $PORT
native_transport_port: $PORT
listen_address: 127.0.0.1
rpc_address: 127.0.0.1
endpoint_snitch: SimpleSnitch
storage_port: 7000
ssl_storage_port: 7001
start_native_transport: true
column_index_size_in_kb: 64
EOF
            # Создаем пустой файл логирования, чтобы Cassandra не ругалась
            touch "$CASS_CONF/logback.xml"
          fi

          # Переменная окружения для Cassandra, чтобы она видела наш конфиг
          export CASSANDRA_CONF="$CASS_CONF"

          echo "--------------------------------------------------------"
          echo " Доступные команды Cassandra-стенда:"
          echo "   start-cass - Запустить локальную Cassandra"
          echo "   stop-cass  - Остановить Cassandra"
          echo "   run-bench  - Сгенерировать данные и собрать блоки (Data.db)"
          echo "--------------------------------------------------------"

          alias start-cass="cassandra -R -p \$CASS_DIR/cassandra.pid > \$CASS_DIR/logs/stdout.log 2>&1"
          alias stop-cass="kill \$(cat \$CASS_DIR/cassandra.pid) && rm \$CASS_DIR/cassandra.pid"
          alias run-bench="python collect_cassandra_blocks.py"
        '';
      };
    };
}
