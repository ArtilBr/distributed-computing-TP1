# Relatório Técnico — Sistema Distribuído de Impressão - Arthur Oliveira e Mateus Gontijo
**Baseado no Algoritmo de Ricart–Agrawala e Relógios de Lamport**

---

## 1. Funcionamento do Código

O sistema foi desenvolvido em **Python** utilizando **gRPC** para comunicação entre processos.  
Há dois tipos de componentes:

- **Servidor de Impressão (“burro”)**  
  Responsável apenas por receber mensagens via `SendToPrinter`, simular o tempo de impressão (2–3s) e retornar uma confirmação.  
  Ele **não participa** da exclusão mútua.

- **Clientes Inteligentes**  
  Cada cliente:
  - Implementa o **serviço gRPC MutualExclusionService**, com os métodos `RequestAccess` e `ReleaseAccess`.
  - Executa o **algoritmo de Ricart–Agrawala**, mantendo um **Relógio de Lamport** para sincronizar eventos.  
  - Atua tanto como **servidor** (para outros clientes) quanto como **cliente** (para peers e para o servidor de impressão).
  - Gera automaticamente jobs de impressão em intervalos aleatórios, solicitando acesso exclusivo antes de cada envio.

Os estados do cliente são:
- `RELEASED`: fora da seção crítica.  
- `WANTED`: deseja entrar na seção crítica (enviou RequestAccess).  
- `HELD`: possui acesso exclusivo (está imprimindo).

A comunicação e sincronização são feitas com **locks** e **condições (Condition)** do módulo `threading`, garantindo exclusão mútua e deferência explícita entre os clientes.

---

## 2. Implementações Principais

### 2.1 Exclusão Mútua (Ricart–Agrawala)
Cada cliente:
1. Envia `RequestAccess` a todos os peers, contendo `(timestamp, id, request_number)`.
2. Aguarda receber **ACK** de todos antes de entrar na seção crítica.
3. Após a impressão, envia `ReleaseAccess` a todos os peers.

O método `RequestAccess` no servidor de cada cliente implementa a **regra de deferência**:
- Se o cliente estiver **HELD** → aguarda liberar a seção crítica.  
- Se estiver **WANTED** e seu pedido for **prioritário** (menor timestamp/id) → também aguarda.  
- Caso contrário → responde imediatamente com `access_granted=True`.

O desbloqueio é feito com `notify_all()` após o término da impressão.

---

### 2.2 Relógio de Lamport
Cada evento local (`tick`) e cada mensagem recebida (`update_on_recv`) atualizam o timestamp lógico.  
Isso garante que todos os pedidos de acesso possam ser ordenados de forma global e consistente.

---

### 2.3 Comunicação gRPC
O sistema utiliza dois serviços:
- `PrintingService`: no servidor burro.
- `MutualExclusionService`: nos clientes.

Os clientes criam canais independentes (`grpc.insecure_channel`) para cada peer e para o servidor de impressão, permitindo chamadas assíncronas via threads.

---

## 3. Análise do Algoritmo de Ricart–Agrawala

O algoritmo implementado garante:
- **Exclusão mútua:** apenas um processo entra na seção crítica por vez.  
- **Ausência de deadlock:** como há uma ordem total definida por `(timestamp, id)`, sempre existe um cliente com prioridade máxima que obtém todos os ACKs.  
- **Equidade:** todos os processos têm chance igual de obter acesso; empates são resolvidos pelo `client_id`.  

A deferência explícita via bloqueio no RPC `RequestAccess` simplifica o controle e evita a necessidade de filas explícitas.

---

## 4. Testes Realizados

### 4.1 Cenário 1 — Funcionamento básico
- Um cliente ativo e um servidor de impressão.  
- O cliente imprime normalmente com timestamps crescentes e confirmações corretas.

### 4.2 Cenário 2 — Concorrência
- Três clientes executando simultaneamente.  
- Somente um entra em estado `HELD` de cada vez.  
- A ordem de impressão segue o menor `(timestamp, id)`, comprovando a exclusão mútua.

### 4.3 Cenário 3 — Falha de cliente
- Um cliente é encerrado durante a execução.  
- Os demais continuam operando após o timeout (120s), sem travar o sistema.

---

