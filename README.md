# 🖨️ Sistema de Impressão Distribuído com Exclusão Mútua (Ricart-Agrawala) e Relógios Lógicos de Lamport

## 🎯 Objetivo
Implementar um sistema distribuído em que múltiplos clientes disputam o **acesso exclusivo** a um recurso compartilhado (um servidor de impressão “burro”), utilizando:
- **gRPC** para comunicação entre processos;
- **Algoritmo de Ricart-Agrawala** para exclusão mútua distribuída;
- **Relógios Lógicos de Lamport** para sincronização e ordenação de eventos.

---

## 🧩 Arquitetura do Sistema

### 🖨️ Servidor de Impressão “Burro”
- Porta padrão: **50051**  
- Recebe requisições de impressão via gRPC (`SendToPrinter`)  
- Exibe no terminal as mensagens recebidas com **ID do cliente** e **timestamp**  
- Simula tempo de impressão (delay de 2–3 segundos)  
- Retorna confirmação da impressão  
- **Não participa** do algoritmo de exclusão mútua  

### 💡 Clientes Inteligentes
- Portas padrão: **50052, 50053, 50054, …**  
- Implementam o algoritmo de **Ricart-Agrawala**  
- Mantêm um **Relógio Lógico de Lamport** atualizado  
- Se comunicam entre si (cliente ↔ cliente) e com o servidor de impressão (cliente → servidor)  
- Geram requisições automáticas de impressão  
- Exibem status e logs no terminal em tempo real  


## 🧠 Algoritmos Implementados

### 🔸 Ricart-Agrawala
- Cada cliente envia `RequestAccess` aos demais quando deseja imprimir.
- A prioridade de acesso é determinada pelo **timestamp lógico** e, em caso de empate, pelo **ID do cliente**.
- Após finalizar a impressão, o cliente envia `ReleaseAccess` para liberar o recurso.

### 🔸 Relógios de Lamport
- Cada evento (envio, recebimento, impressão) incrementa o relógio lógico.
- Garante **ordenação causal** entre eventos distribuídos.

---

## 🛠️ Configuração do Ambiente

### 1️⃣ Instalar dependências
```bash
python -m pip install grpcio grpcio-tools
```

### 2️⃣ Gerar código gRPC a partir do `.proto`
```bash
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. printing.proto
```

Isso gerará os arquivos:
- `printing_pb2.py`
- `printing_pb2_grpc.py`

---

## 🚀 Execução do Sistema

### 🖨️ 1. Servidor de Impressão “Burro” (Terminal 1)
```bash
python printer_server.py --port 50051
```

### 💻 2. Cliente 1 (Terminal 2)
```bash
python printing_client.py --id 1 --server localhost:50051 --port 50052 --clients localhost:50053,localhost:50054 --active
```

### 💻 3. Cliente 2 (Terminal 3)
```bash
python printing_client.py --id 2 --server localhost:50051 --port 50053 --clients localhost:50052,localhost:50054 --active
```

### 💻 4. Cliente 3 (Terminal 4)
```bash
python printing_client.py --id 3 --server localhost:50051 --port 50054 --clients localhost:50052,localhost:50053 --active
```

> Use `--active` para iniciar as requisições automáticas de impressão.  
> Caso queira controlar manualmente, remova o parâmetro `--active`.

---

## 🧪 Casos de Teste

### ✅ Cenário 1 – Sem Concorrência
1. Apenas um cliente executando (`--active`).
2. Cliente envia requisição → entra na seção crítica → imprime.
3. Servidor de impressão exibe a mensagem e retorna confirmação.

### ⚔️ Cenário 2 – Com Concorrência
1. Dois ou mais clientes solicitam impressão simultaneamente.
2. O algoritmo de **Ricart-Agrawala** define quem imprime primeiro, com base no timestamp lógico.
3. A ordem de impressão segue a ordenação garantida pelos **relógios de Lamport**.

---

## 🧾 Exemplo de Saída

### 🖨️ Servidor
```
[TS: 17] CLIENTE 2 (req #4): Olá do cliente 2 (job 4)
[TS: 19] CLIENTE 1 (req #5): Olá do cliente 1 (job 5)
```

### 💻 Cliente
```
[Client 1] Solicitando acesso à CS (req #5)
[Client 1] -> entrou na CS (req #5)
[Client 1] Confirmação impressora: Impresso (cliente 1, req 5)
[Client 1] <- saindo da CS (req #5)
```

---

## 📊 Critérios de Avaliação

| Critério | Peso | Descrição |
|-----------|-------|-----------|
| Corretude do algoritmo | 30% | Implementação correta de Ricart-Agrawala |
| Sincronização de relógios | 20% | Implementação correta de Lamport |
| Comunicação cliente-servidor | 10% | Uso correto do PrintingService |
| Comunicação cliente-cliente | 10% | Uso correto do MutualExclusionService |
| Execução distribuída | 10% | Funcionamento em múltiplos terminais |
| Código e documentação | 20% | Clareza do código e explicação técnica |

---

## 📦 Entregáveis

- Código-fonte completo (`.py` e `.proto`)
- **Manual de execução** (README.md)
- **Relatório técnico**, contendo:
  - Arquitetura e funcionamento do sistema
  - Explicação do algoritmo Ricart-Agrawala
  - Sincronização com relógios de Lamport
  - Resultados de testes
  - Dificuldades e soluções adotadas

---

## 🧑‍💻 Autores
Projeto desenvolvido como parte da disciplina de **Sistemas Distribuídos**, com implementação em **Python 3.x + gRPC**.

---
