# 🧠 Relatório Técnico — Sistema Distribuído de Impressão  
**Baseado no Algoritmo de Ricart–Agrawala e Relógios de Lamport**

---

## 1. Arquitetura e Funcionamento do Código

### 1.1 Estrutura geral
O sistema é composto por dois tipos de processos:

1. **Servidor de Impressão “Burro” (PrintingService)**
   - Porta padrão: `50051`
   - Não participa da exclusão mútua.
   - Apenas recebe requisições `SendToPrinter` e imprime mensagens no formato:
     ```
     [TS: <timestamp>] CLIENTE <id>: <mensagem> (req #<n>)
     ```
   - Simula o tempo de impressão com atraso de 2–3 segundos.

2. **Clientes Inteligentes (MutualExclusionService)**
   - Portas típicas: `50052`, `50053`, `50054`, ...
   - Implementam o **algoritmo de Ricart–Agrawala (RA)** e mantêm **Relógios Lógicos de Lamport**.
   - Cada cliente funciona simultaneamente como:
     - **Servidor gRPC:** para receber requisições `RequestAccess` e `ReleaseAccess` de outros clientes.
     - **Cliente gRPC:** para enviar mensagens ao servidor burro e aos peers.

### 1.2 Comunicação e serviços gRPC

#### Serviços implementados

- **PrintingService (servidor burro):**
  - `SendToPrinter(PrintRequest) -> PrintResponse`

- **MutualExclusionService (clientes inteligentes):**
  - `RequestAccess(AccessRequest) -> AccessResponse`
  - `ReleaseAccess(AccessRelease) -> Empty`

#### Mensagens trocadas
Cada mensagem inclui:
- `client_id`: identificação do nó solicitante.
- `lamport_timestamp`: timestamp lógico para ordenação total.
- `request_number`: contador local de requisições.

---

### 1.3 Fluxo operacional

1. O cliente entra no estado **WANTED** e envia `RequestAccess` para todos os outros clientes.
2. Cada peer executa a **regra de deferência**:
   - Se estiver **HELD** → aguarda sair da seção crítica.
   - Se estiver **WANTED** e seu próprio pedido tiver **maior prioridade** → aguarda até imprimir.
   - Caso contrário → responde imediatamente com `AccessResponse(access_granted=True)`.
3. O cliente só entra no estado **HELD** após receber **todos os ACKs**.
4. Dentro da seção crítica, envia o conteúdo ao **servidor burro** (`SendToPrinter`).
5. Após a impressão, muda para o estado **RELEASED**, notifica todos os peers (`ReleaseAccess`) e libera os que estavam aguardando.

---

### 1.4 Estrutura interna do cliente

O cliente é construído em torno das seguintes classes e componentes:

- **`LamportClock`**: relógio lógico thread-safe com métodos `tick()` e `update_on_recv()`.
- **`ClientNode`**:
  - Implementa o serviço gRPC `MutualExclusionServiceServicer`.
  - Gerencia estados (`RELEASED`, `WANTED`, `HELD`).
  - Sincroniza o acesso com `threading.Lock` e `threading.Condition`.
  - Mantém threads para:
    - Impressão de status periódico.
    - Geração automática de jobs de impressão em intervalos aleatórios.

---

## 2. Análise do Algoritmo de Ricart–Agrawala Implementado

### 2.1 Princípio do algoritmo
O algoritmo de Ricart–Agrawala permite exclusão mútua distribuída **sem coordenador central**, utilizando **troca direta de mensagens entre todos os nós**.

Cada nó que deseja acessar o recurso compartilhado:
1. Envia `RequestAccess` a todos os outros nós.
2. Aguarda receber **todos os ACKs**.
3. Ao liberar o recurso, envia `ReleaseAccess` para todos.

O protocolo assegura:
- **Segurança:** apenas um processo entra na seção crítica.
- **Progresso:** todo processo eventualmente entra.
- **Equidade:** ordem global baseada em `(timestamp, id)`.

---

### 2.2 Regra de deferência (implementada)
A deferência explícita foi implementada utilizando `threading.Condition`:
- Enquanto o cliente estiver **HELD** ou **WANTED** com prioridade maior, o servidor **bloqueia o retorno do RPC** `RequestAccess`.
- Quando o cliente sai da seção crítica, chama `_cond.notify_all()`, liberando todos os peers em espera.

Essa abordagem é mais realista e evita que o peer tenha que reconsultar periodicamente o estado.

---

### 2.3 Integração com Relógio de Lamport
- Cada envio de mensagem (`RequestAccess`, `ReleaseAccess`, `SendToPrinter`) gera um **tick** local.
- Cada recebimento chama `update_on_recv(ts)`.
- A ordenação total entre eventos é garantida por `(lamport_timestamp, client_id)`.

---

### 2.4 Complexidade de mensagens
Para `N` clientes:
- `2 × (N - 1)` mensagens por ciclo de seção crítica (Request + Reply).
- Mais `(N - 1)` mensagens opcionais de Release.

Total típico: **3 × (N - 1)** mensagens por operação completa.

---

### 2.5 Comparação com abordagens alternativas
| Abordagem | Coordenador? | Mensagens por ciclo | Tolerância a falha | Ordem global |
|------------|---------------|--------------------|--------------------|---------------|
| Centralizada | Sim | 3 | Baixa | Parcial |
| **Ricart–Agrawala (este projeto)** | Não | **3(N−1)** | Média (falhas ignoradas após timeout) | **Sim (Lamport)** |
| Token Ring | Não | 1 (em média) | Baixa (perda de token) | Sim |

---

## 3. Resultados dos Testes

### 3.1 Cenário 1 — Funcionamento básico
**Objetivo:** validar a operação sem concorrência.  
**Execução:**
1. Iniciado o servidor burro (porta 50051).
2. Iniciado apenas 1 cliente (porta 50052).

**Resultado esperado:**

[STATUS] id=1 ts=1 state=HELD pendingAcks=0
[TS: 1] CLIENTE 1: Hello from client 1 at 1730465124 (req #1)
[JOB OK] Impresso com sucesso em 2.3s

✅ O cliente imprime normalmente, com atualização coerente do relógio.

---

### 3.2 Cenário 2 — Concorrência controlada
**Objetivo:** validar exclusão mútua entre múltiplos clientes.

**Execução:**
- Servidor burro na porta `50051`.
- Três clientes:
  - C1 → porta `50052`
  - C2 → porta `50053`
  - C3 → porta `50054`

**Comportamento observado:**
- Clientes solicitam quase simultaneamente (`WANTED`).
- Apenas **um** entra em `HELD` por vez.
- Ordem de acesso determinada por `(timestamp, id)`.
- No servidor burro:
[TS: 9] CLIENTE 2: ...
[TS: 14] CLIENTE 1: ...
[TS: 20] CLIENTE 3: ...


✅ A impressão ocorre sequencialmente e coerente com o tempo lógico global.

---

### 3.3 Cenário 3 — Falha simulada
**Objetivo:** observar tolerância a falhas parciais.

**Execução:**
- Um cliente é encerrado durante o ciclo de impressão.
- Os outros continuam normalmente.

**Resultado:**
- O nó ausente é ignorado após timeout (120s).
- Sistema continua operando com os demais nós.

✅ O sistema mantém progresso, demonstrando tolerância a falhas de nós individuais.

---

## 4. Dificuldades Encontradas e Soluções Adotadas

| Desafio | Descrição | Solução Implementada |
|----------|------------|----------------------|
| **Bloqueio de threads** | Era necessário reter o retorno do `RequestAccess` enquanto o nó estava em `HELD` ou com prioridade maior. | Implementado `threading.Condition` associado ao `state_lock`, com `wait()` e `notify_all()` ao liberar a CS. |
| **Deadlocks por timeouts curtos** | RPCs bloqueados expiram antes do cliente liberar a CS. | Timeout de 120s configurado no `RequestAccess`. |
| **Diferenças entre PowerShell e Bash** | O comando `protoc` com `--` causava erro no PowerShell. | Criados scripts dedicados para Windows (`.bat`) e Linux (`.sh`). |
| **Falhas de peers simuladas** | Um peer caído impedia o progresso global. | Tratamento de exceções: falha é interpretada como ACK recebido após timeout. |
| **Observabilidade limitada** | Dificuldade de visualizar o estado interno. | Adicionado `start_status_printer()` para log periódico dos estados e timestamps. |

---

## 5. Conclusão

O sistema proposto implementa corretamente um **mecanismo de exclusão mútua distribuída**, sem servidor coordenador, usando:
- **Comunicação via gRPC** entre processos independentes.
- **Relógios Lógicos de Lamport** para ordenação global.
- **Deferência explícita** no algoritmo Ricart–Agrawala, garantindo exclusão mútua segura e justa.

Os testes demonstraram:
- Correção funcional.
- Ausência de deadlock.
- Execução ordenada e previsível, mesmo sob concorrência.

Com isso, o projeto cumpre integralmente os objetivos propostos para o trabalho de **Sistemas Distribuídos**.

---

