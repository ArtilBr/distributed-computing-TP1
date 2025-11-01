"""
ClientNode: nó cliente "inteligente" que implementa:
- Exclusão mútua distribuída via Ricart–Agrawala (RA) com deferência explícita
- Relógios Lógicos de Lamport
- gRPC para conversar com outros clientes (RequestAccess/ReleaseAccess) e com o "servidor de impressão burro"

Observação de projeto:
- A deferência explícita é feita retendo o retorno do RPC RequestAccess enquanto:
  (a) estou na seção crítica (HELD), ou
  (b) estou querendo entrar (WANTED) e meu pedido tem prioridade sobre o do chamador.
- A prioridade segue (lamport_timestamp, client_id) — menor vence; empate pelo id.
"""

from __future__ import annotations

import argparse
import random
import threading
import time
from concurrent import futures
from enum import Enum
from typing import Optional, Tuple, Dict, List

import grpc
import distributed_printing_pb2 as pb2
import distributed_printing_pb2_grpc as pb2_grpc


# ==========================
# Constantes de configuração
# ==========================
# Tempo máximo que um peer pode segurar a resposta do RequestAccess (deferência) antes do solicitante estourar timeout.
ACK_TIMEOUT_SEC: float = 120.0

# Tempo máximo para enviar o ReleaseAccess e não travar finalização.
RELEASE_TIMEOUT_SEC: float = 5.0

# Tempo máximo para esperar resposta do servidor de impressão "burro".
PRINTER_TIMEOUT_SEC: float = 15.0


# ========================================
# Relógio de Lamport (thread-safe / simples)
# ========================================
class LamportClock:
    """Relógio lógico de Lamport com operações atômicas."""

    def __init__(self) -> None:
        self._ts: int = 0
        self._lock = threading.Lock()

    def tick(self) -> int:
        """Evento local: incrementa o relógio e retorna o novo valor."""
        with self._lock:
            self._ts += 1
            return self._ts

    def update_on_recv(self, incoming_ts: int) -> int:
        """
        Evento de recebimento: ajusta o relógio para max(local, recebido) + 1
        e retorna o novo valor.
        """
        with self._lock:
            self._ts = max(self._ts, incoming_ts) + 1
            return self._ts

    @property
    def value(self) -> int:
        """Leitura segura do timestamp atual."""
        with self._lock:
            return self._ts


# ===========================
# Estados do algoritmo de RA
# ===========================
class RAState(Enum):
    RELEASED = 0  # não precisa da CS (critical section)
    WANTED = 1    # quer entrar na CS (já enviou RequestAccess)
    HELD = 2      # está na CS (acesso exclusivo)


# ==========================
# Nó cliente (servidor RA)
# ==========================
class ClientNode(pb2_grpc.MutualExclusionServiceServicer):
    """
    Implementa o serviço MutualExclusionService de RA para receber solicitações dos peers,
    e também atua como cliente gRPC para:
      - pedir acesso aos peers (RequestAccess)
      - notificar liberação aos peers (ReleaseAccess)
      - enviar a impressão ao servidor burro (PrintingService)
    """

    def __init__(
        self,
        client_id: int,
        host: str,
        port: int,
        peers: List[str],
        printer_addr: str,
    ) -> None:
        # Identificação e networking
        self.client_id: int = client_id
        self.host: str = host
        self.port: int = port
        self.peers: List[str] = peers  # lista "host:port" de OUTROS clientes
        self.printer_addr: str = printer_addr

        # Canais/stubs para peers (MutualExclusionService) e impressora (PrintingService)
        self._peer_stubs: Dict[str, pb2_grpc.MutualExclusionServiceStub] = {}
        for peer in self.peers:
            ch = grpc.insecure_channel(peer)
            self._peer_stubs[peer] = pb2_grpc.MutualExclusionServiceStub(ch)

        self._printer_channel = grpc.insecure_channel(self.printer_addr)
        self._printer_stub = pb2_grpc.PrintingServiceStub(self._printer_channel)

        # Algoritmo RA + Lamport
        self.clock = LamportClock()
        self.state: RAState = RAState.RELEASED
        self.state_lock = threading.Lock()  # protege state, my_request, pending_acks

        # Pedido atual do nó: (lamport_ts, client_id, request_number)
        self.my_request: Optional[Tuple[int, int, int]] = None
        self.request_number: int = 0

        # Condition para deferência explícita (bloquear respostas a peers)
        self._cond = threading.Condition(self.state_lock)

        # Acks em aberto e evento para aguardar todos
        self.pending_acks: int = 0
        self.all_acks_event = threading.Event()

        # Métrica simples
        self._jobs_sent: int = 0

    # =====================================================
    # Métodos do serviço gRPC (servidor): recebendo de peers
    # =====================================================
    def RequestAccess(self, request: pb2.AccessRequest, context) -> pb2.AccessResponse:
        """
        Recebe o pedido de acesso de um peer.
        Regra de deferência do RA:
          - Se EU estiver HELD -> bloqueio a resposta (deferir).
          - Se EU estiver WANTED e MEU pedido tiver prioridade -> bloqueio a resposta (deferir).
          - Caso contrário -> respondo imediatamente com ACK.
        """
        # Ajuste de Lamport com timestamp recebido
        self.clock.update_on_recv(request.lamport_timestamp)

        peer_id = request.client_id
        their_req = (request.lamport_timestamp, peer_id, request.request_number)

        with self._cond:
            while True:
                # 1) Estou NA seção crítica? Então ninguém entra -> espero sair.
                if self.state == RAState.HELD:
                    self._cond.wait(timeout=0.1)
                    continue

                # 2) Estou QUERENDO entrar e meu pedido tem maior prioridade que o do peer?
                #    Se sim, aguardo até eu terminar (mantém o peer esperando).
                if self.state == RAState.WANTED and self._is_my_request_higher_priority_than(their_req):
                    self._cond.wait(timeout=0.1)
                    continue

                # 3) Caso contrário, posso responder agora.
                break

            # Tick ao enviar a resposta (evento local)
            self.clock.tick()
            return pb2.AccessResponse(access_granted=True, lamport_timestamp=self.clock.value)

    def ReleaseAccess(self, request: pb2.AccessRelease, context) -> pb2.Empty:
        """
        Recebe a notificação de liberação de um peer.
        Aqui sincronizamos apenas o relógio de Lamport; não é necessário
        manter fila de pedidos do outro lado pois a deferência é feita via bloqueio.
        """
        self.clock.update_on_recv(request.lamport_timestamp)
        return pb2.Empty()

    # ===========================================
    # Auxiliar: prioridade (menor ts; desempate id)
    # ===========================================
    def _is_my_request_higher_priority_than(self, their_req: Tuple[int, int, int]) -> bool:
        """
        Retorna True se MEU pedido atual tem prioridade sobre o do peer:
          - prioridade por menor timestamp
          - em empate, menor client_id
        """
        my_req = self.my_request
        if my_req is None:
            return False
        return (my_req[0], my_req[1]) < (their_req[0], their_req[1])

    # ==================================================
    # Cliente: broadcast de RequestAccess e ReleaseAccess
    # ==================================================
    def _broadcast_request(self) -> None:
        """Envia RequestAccess a todos os peers e aguarda ACKs (via evento)."""
        self.pending_acks = len(self.peers)
        self.all_acks_event.clear()

        req = pb2.AccessRequest(
            client_id=self.client_id,
            lamport_timestamp=self.clock.tick(),  # evento local ao enviar
            request_number=self.request_number,
        )

        for peer_addr, stub in self._peer_stubs.items():
            # Cada request vai em uma thread para não bloquear o chamador
            t = threading.Thread(
                target=self._send_request_to_peer,
                args=(stub, peer_addr, req),
                daemon=True,
            )
            t.start()

    def _send_request_to_peer(
        self,
        stub: pb2_grpc.MutualExclusionServiceStub,
        peer_addr: str,
        req: pb2.AccessRequest,
    ) -> None:
        """Faz a chamada RPC a um peer e contabiliza o ACK (com tolerância a falhas)."""
        try:
            # O peer pode segurar a resposta (deferência) por estar HELD/WANTED.
            resp = stub.RequestAccess(req, timeout=ACK_TIMEOUT_SEC)
            self.clock.update_on_recv(resp.lamport_timestamp)
        except Exception:
            # Tolerância didática: se um peer cair, não travamos para sempre.
            # Em produção, preferir membership/remoção do conjunto de peers.
            pass
        finally:
            # Contabiliza o ACK (ou tolerância) e dispara o evento quando zerar.
            with self.state_lock:
                self.pending_acks -= 1
                if self.pending_acks == 0:
                    self.all_acks_event.set()

    def _broadcast_release(self) -> None:
        """Notifica todos os peers de que sai da CS."""
        rel = pb2.AccessRelease(
            client_id=self.client_id,
            lamport_timestamp=self.clock.tick(),
            request_number=self.request_number,
        )
        for stub in self._peer_stubs.values():
            t = threading.Thread(target=self._safe_release, args=(stub, rel), daemon=True)
            t.start()

    @staticmethod
    def _safe_release(stub: pb2_grpc.MutualExclusionServiceStub, rel: pb2.AccessRelease) -> None:
        """Chamada ReleaseAccess tolerante a falhas/timeout (não deve travar a saída)."""
        try:
            stub.ReleaseAccess(rel, timeout=RELEASE_TIMEOUT_SEC)
        except Exception:
            pass

    # ==========================
    # Seção crítica: impressão
    # ==========================
    def _critical_section_print(self, msg: str) -> Tuple[bool, str]:
        """
        Envia a requisição de impressão ao servidor "burro".
        Retorna (sucesso, mensagem_de_confirmação_ou_erro).
        """
        req = pb2.PrintRequest(
            client_id=self.client_id,
            message_content=msg,
            lamport_timestamp=self.clock.tick(),
            request_number=self.request_number,
        )
        try:
            resp = self._printer_stub.SendToPrinter(req, timeout=PRINTER_TIMEOUT_SEC)
            self.clock.update_on_recv(resp.lamport_timestamp)
            return resp.success, resp.confirmation_message
        except Exception as e:
            return False, f"Falha ao imprimir: {e}"

    # ==========================================
    # Ciclo completo: pedir -> esperar -> SC -> liberar
    # ==========================================
    def request_and_print(self, content: str) -> Tuple[bool, str]:
        """Fluxo principal de RA + Lamport para imprimir uma mensagem."""
        # 1) Anunciar intenção (WANTED), registrar meu pedido e broadcast
        with self.state_lock:
            self.state = RAState.WANTED
            self.request_number += 1
            self.my_request = (self.clock.tick(), self.client_id, self.request_number)

        self._broadcast_request()

        # 2) Esperar TODOS os ACKs
        if not self.all_acks_event.wait(timeout=ACK_TIMEOUT_SEC + 60.0):
            return False, "Timeout aguardando ACKs dos peers"

        # 3) Entrar na seção crítica
        with self.state_lock:
            self.state = RAState.HELD

        ok, info = self._critical_section_print(content)

        # 4) Sair da Seção Critica, notificar quem estava deferido e broadcast release
        with self._cond:
            self.state = RAState.RELEASED
            self.my_request = None
            self._cond.notify_all()  # acorda handlers RequestAccess bloqueados

        self._broadcast_release()
        return ok, info

    # =====================
    # Utils
    # =====================
    def start_status_printer(self, interval: float = 2.0) -> None:
        """Imprime periodicamente o estado local (debug/observabilidade)."""

        def _loop() -> None:
            while True:
                with self.state_lock:
                    st = self.state.name
                    ts = self.clock.value
                    p_acks = self.pending_acks
                print(
                    f"[STATUS] id={self.client_id} ts={ts} "
                    f"state={st} pendingAcks={p_acks} jobsSent={self._jobs_sent}"
                )
                time.sleep(interval)

        threading.Thread(target=_loop, daemon=True).start()

    def start_job_generator(self, min_wait: float = 3.0, max_wait: float = 7.0) -> None:
        """Gera jobs aleatórios continuamente, simulando requisições de impressão."""

        def _loop() -> None:
            while True:
                time.sleep(random.uniform(min_wait, max_wait))
                job_msg = f"Hello from client {self.client_id} at {time.time():.0f}"
                ok, info = self.request_and_print(job_msg)
                self._jobs_sent += 1
                if ok:
                    print(f"[JOB OK] {info}")
                else:
                    print(f"[JOB ERR] {info}")

        threading.Thread(target=_loop, daemon=True).start()

    # ==========================
    # Servidor gRPC do cliente
    # ==========================
    def serve(self):
        """Sobe o servidor gRPC (MutualExclusionService) local do cliente."""
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=32))
        pb2_grpc.add_MutualExclusionServiceServicer_to_server(self, server)
        server.add_insecure_port(f"{self.host}:{self.port}")
        server.start()
        print(
            f"Cliente {self.client_id} ouvindo RA em {self.host}:{self.port} | "
            f"impressora={self.printer_addr} | peers={self.peers}"
        )
        return server


# ======================
# CLI e entrypoint main
# ======================
def parse_args():
    """Argumentos de linha de comando do cliente."""
    p = argparse.ArgumentParser(
        description="Cliente inteligente com Ricart–Agrawala e relógio de Lamport"
    )
    p.add_argument("--id", type=int, required=True, help="Identificador único do cliente (int)")
    p.add_argument("--host", default="0.0.0.0", help="Host de bind (default 0.0.0.0)")
    p.add_argument("--port", type=int, required=True, help="Porta do servidor RA local (ex: 50052)")
    p.add_argument(
        "--peers",
        default="",
        help="Lista de peers separados por vírgula (ex: localhost:50053,localhost:50054)",
    )
    p.add_argument("--printer", default="localhost:50051", help="Endereço do servidor de impressão")
    p.add_argument("--min-wait", type=float, default=3.0, help="Tempo mínimo entre jobs automáticos")
    p.add_argument("--max-wait", type=float, default=7.0, help="Tempo máximo entre jobs automáticos")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    peers = [s.strip() for s in args.peers.split(",") if s.strip()]

    node = ClientNode(
        client_id=args.id,
        host=args.host,
        port=args.port,
        peers=peers,
        printer_addr=args.printer,
    )
    server = node.serve()

    node.start_status_printer(interval=2.0)
    node.start_job_generator(min_wait=args.min_wait, max_wait=args.max_wait)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == "__main__":
    main()
