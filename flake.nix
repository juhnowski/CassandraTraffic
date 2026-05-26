{
  description = "Стенд для сбора сырых несжатых SSTables Apache Cassandra";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      
      pythonEnv = pkgs.python3.withPackages (ps: [
        ps.cassandra-driver
      ]);
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [
          pkgs.cassandra_4
          pkgs.openjdk11_headless  # Жестко фиксируем стабильную Java 11
          pythonEnv
        ];

        shellHook = ''
          echo "--------------------------------------------------------"
          echo " Стенд Cassandra готов к работе."
          echo " Запустите тесты командой:"
          echo "   run-bench"
          echo "--------------------------------------------------------"

          alias run-bench="python collect_cassandra_blocks.py"
        '';
      };
    };
}
