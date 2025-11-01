# ⚙️ Manual Simples de Instalação e Execução  
**Sistema Distribuído de Impressão — Ricart–Agrawala + Lamport**

---

## 1. Pré-requisitos

Antes de iniciar, verifique se o ambiente possui:

- **Python 3.9** ou superior  
- **pip** instalado  
- Conexão local (os processos usam `localhost`)

---

## 2. Instalação das Dependências

Na pasta principal do projeto, execute:

```bash
python -m pip install -r requirements.txt
```

Isso instalará os pacotes:
- `grpcio`
- `grpcio-tools`

---

## 3. Geração dos Arquivos gRPC

O projeto usa um arquivo `.proto` para definir as mensagens e serviços.  
Antes de rodar o sistema, é necessário gerar os arquivos Python correspondentes.

### 🔹 Windows (PowerShell ou CMD)
```powershell
python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/distributed_printing.proto
```

### 🔹 Linux / macOS / WSL
```bash
python -m grpc_tools.protoc   -I proto   --python_out=.   --grpc_python_out=.   proto/distributed_printing.proto
```

Serão criados dois arquivos:
```
distributed_printing_pb2.py
distributed_printing_pb2_grpc.py
```

---

## 4. Execução do Sistema

O sistema possui dois tipos de processos:  
1. **Servidor de Impressão (burro)**  
2. **Clientes Inteligentes (com Ricart–Agrawala)**

### 🖨️ Iniciando o Servidor de Impressão
Em um terminal separado, execute:
```bash
python printer_server.py
```

Saída esperada:
```
Servidor de impressão burro rodando em 0.0.0.0:50051
```

---

### 🤝 Iniciando os Clientes
Cada cliente deve rodar em um terminal diferente.

Exemplo com **3 clientes**:

```bash
python client_node.py --id 1 --port 50052 --peers localhost:50053,localhost:50054 --printer localhost:50051
python client_node.py --id 2 --port 50053 --peers localhost:50052,localhost:50054 --printer localhost:50051
python client_node.py --id 3 --port 50054 --peers localhost:50052,localhost:50053 --printer localhost:50051
```

Os clientes começarão a:
- Solicitar acesso exclusivo entre si usando Ricart–Agrawala  
- Enviar mensagens para o servidor de impressão  
- Imprimir periodicamente logs como:
  ```
  [STATUS] id=1 ts=23 state=HELD pendingAcks=0 jobsSent=5
  [JOB OK] Impresso com sucesso em 2.4s
  ```

---

## 5. Funcionamento do Algoritmo

1. Cada cliente solicita acesso (`RequestAccess`) a todos os outros.  
2. Espera receber **ACKs** de todos antes de imprimir.  
3. Após a impressão, envia (`ReleaseAccess`) liberando o recurso.  
4. A prioridade entre clientes é definida por `(timestamp lógico, id)`.

Assim, **nunca há dois clientes imprimindo ao mesmo tempo**.

---

## 6. Encerramento

Para finalizar:
- Pressione `Ctrl + C` em cada terminal.  
- Ou feche as janelas de execução.

---

## 7. Resultado Esperado

O servidor exibirá mensagens ordenadas conforme os timestamps lógicos:
```
[TS: 7] CLIENTE 2: Hello from client 2 at 1730465230 (req #1)
[TS: 10] CLIENTE 1: Hello from client 1 at 1730465233 (req #1)
[TS: 14] CLIENTE 3: Hello from client 3 at 1730465237 (req #1)
```

✅ Apenas um cliente imprime por vez, comprovando a exclusão mútua distribuída.

---
