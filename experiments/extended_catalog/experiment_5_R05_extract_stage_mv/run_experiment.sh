#!/bin/bash

# Script de Reprodução para a Regra R05
echo "--- Iniciando a análise de segurança para R05 ---"

# 1. Build das imagens
docker build -t r05-before -f R05_cargo_before.Dockerfile .
docker build -t r05-after -f R05_cargo_after.Dockerfile .

# 2. Executar Scans com Trivy
echo "A executar scans..."
trivy image --scanners vuln r05-before > log_before.txt
trivy image --scanners vuln r05-after > log_after.txt

echo "--- Concluído. Logs gerados: log_before.txt e log_after.txt ---"
