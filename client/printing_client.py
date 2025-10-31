import argparse
import threading
import time
import random

import grpc
from concurrent import futures

import printing_pb2
import printing_pb2_grpc


# ---------------------------
# Utilitários: Lamport Clock
# ---------------------------
class LamportClock:
    def __init__(self):
        self.lock = threading.Lock()
        self.ts = 0

    def tick(self) -> int:
        with self.lock:
            self.ts += 1
            return self.ts

    def recv(self, other_ts: int) -> int:
        with self.lock:
            self.ts = max(self.ts, other_ts) + 1
            return self.ts

    def peek(self) -> int:
        with self.lock:
            return self.ts


# ----------------------------------------------------
# Cliente/Servidor P2P com Ricart–Agrawala
# ----------------------------------------------------
class RAClient(printing_pb2_grpc.MutualExclusionServiceServicer):
    def __init__(self, client_id: int, my_addr: str, peers: list[str], printer_addr: str):
        self.client_id = client_id
        self.my_addr = my_addr
        self.peers = peers  # ex.: ["localhost:50053", "localhost:50054"]
        self.printer_addr = printer_addr

        # Ricart–Agrawala state
        self.clock = LamportClock()
        self.requesting_cs = False
        self.request_ts = None
        self.request_number = 0
        self.deferred_replies = set()
        self.outstanding_replies = set()

        # gRPC server para receber requests dos pares
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        printing_pb2_grpc.add_MutualExclusionServiceServicer_to_server(self, self.server)
        self.server.add_insecure_port(self.my_addr)

        # canais/stubs para pares e para a impressora
        self.peer_channels = {}
        self.peer_stubs = {}
        for p in self.peers:
            ch = grpc.insecure_channel(p)
            self.peer_channels[p] = ch
            self.peer_stubs[p] = printing_pb2_grpc.MutualExclusionServiceStub(ch)

        self.printer_channel = grpc.insecure_channel(self.printer_addr)
        self.printer_stub = printing_pb2_grpc.PrintingServiceStub(self.printer_channel)

        self.state_lock = threading.Lock()

    # ------------- Servidor gRPC (PARES) -------------
    def RequestAccess(self, request, context):
        # Atualiza Lamport com timestamp recebido
        self.clock.recv(request.lamport_timestamp)

        # Regra Ricart–Agrawala:
        # Conceder se NÃO estou requisitando OU (estou requisitando, mas meu timestamp é maior
        # ou igual e em caso de empate, meu id é maior) -> prioridade ao menor (ts,id)
        with self.state_lock:
            grant = False
            if not self.requesting_cs:
                grant = True
            else:
                my_key = (self.request_ts, self.client_id)
                other_key = (request.lamport_timestamp, request.client_id)
                if my_key > other_key:
                    grant = True
                else:
                    self.deferred_replies.add(request.client_id)

        return printing_pb2.AccessResponse(
            access_granted=grant,
            lamport_timestamp=self.clock.tick(),
        )

    def ReleaseAccess(self, request, context):
        # Atualiza Lamport com timestamp recebido
        self.clock.recv(request.lamport_timestamp)
        # Liberação: ao receber release de outro, se eu estava aguardando reply dele, removo
        with self.state_lock:
            if request.client_id in self.outstanding_replies:
                self.outstanding_replies.discard(request.client_id)
        return printing_pb2.Empty()

    # ------------- Cliente gRPC (PARES) -------------
    def broadcast_request(self):
        with self.state_lock:
            self.requesting_cs = True
            self.request_number += 1
            self.request_ts = self.clock.tick()
            self.deferred_replies.clear()
            # preciso de replies de todos os outros
            self.outstanding_replies = {self._peer_id(addr) for addr in self.peers}

        req = printing_pb2.AccessRequest(
            client_id=self.client_id,
            lamport_timestamp=self.request_ts,
            request_number=self.request_number
        )

        def send_one(addr):
            try:
                resp = self.peer_stubs[addr].RequestAccess(req, timeout=5)
                self.clock.recv(resp.lamport_timestamp)
                if resp.access_granted:
                    with self.state_lock:
                        self.outstanding_replies.discard(self._peer_id(addr))
            except Exception as e:
                print(f"[Client {self.client_id}] Falha ao contatar {addr}: {e}")

        threads = []
        for addr in self.peers:
            t = threading.Thread(target=send_one, args=(addr,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

    def broadcast_release(self):
        # Envia release para todos
        rel = printing_pb2.AccessRelease(
            client_id=self.client_id,
            lamport_timestamp=self.clock.tick(),
            request_number=self.request_number
        )
        def send_one(addr):
            try:
                self.peer_stubs[addr].ReleaseAccess(rel, timeout=5)
            except Exception as e:
                print(f"[Client {self.client_id}] Falha ao enviar release para {addr}: {e}")
        threads = []
        for addr in self.peers:
            t = threading.Thread(target=send_one, args=(addr,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        with self.state_lock:
            self.requesting_cs = False
            self.request_ts = None
            self.outstanding_replies.clear()
            # Envia "replies" implícitos aos diferidos liberando o acesso
            # (no nosso protocolo, o Release sinaliza a liberação global)

    def _peer_id(self, addr: str) -> int:
        # Convenção simples para extrair um id “numérico” do peer só para controle do set:
        # ex.: "localhost:50053" -> 50053
        try:
            return int(addr.split(":")[-1])
        except:
            return hash(addr) & 0x7FFFFFFF

    # ------------- Seção Crítica (imprimir) -------------
    def enter_critical_section(self):
        # espera até receber todos os replies
        while True:
            with self.state_lock:
                done = (len(self.outstanding_replies) == 0)
            if done:
                break
            time.sleep(0.05)

    def do_print(self, content: str):
        # Chama o servidor burro
        req = printing_pb2.PrintRequest(
            client_id=self.client_id,
            message_content=content,
            lamport_timestamp=self.clock.tick(),
            request_number=self.request_number
        )
        resp = self.printer_stub.SendToPrinter(req, timeout=10)
        # Ajusta Lamport com timestamp do retorno (apenas informativo)
        self.clock.recv(resp.lamport_timestamp)
        print(f"[Client {self.client_id}] Confirmação impressora: {resp.confirmation_message}")

    # ------------- Loop de trabalho -------------
    def start_server(self):
        self.server.start()
        print(f"[Client {self.client_id}] Servidor P2P em {self.my_addr}")

    def wait_server(self):
        self.server.wait_for_termination()

    def run_workload(self, min_delay=2, max_delay=5):
        # Gera requisições de impressão automaticamente
        i = 0
        while True:
            time.sleep(random.uniform(min_delay, max_delay))
            i += 1
            msg = f"Olá do cliente {self.client_id} (job {i})"

            print(f"[Client {self.client_id}] Solicitando acesso à CS (req #{i})")
            self.broadcast_request()
            self.enter_critical_section()
            print(f"[Client {self.client_id}] -> entrou na CS (req #{i})")

            # seção crítica: imprimir
            try:
                self.do_print(msg)
            finally:
                print(f"[Client {self.client_id}] <- saindo da CS (req #{i})")
                self.broadcast_release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, help="ID do cliente")
    parser.add_argument("--port", type=int, required=True, help="porta local (ex.: 50052)")
    parser.add_argument("--server", type=str, default="localhost:50051", help="endereço do servidor burro")
    parser.add_argument("--clients", type=str, default="", help="lista de peers separados por vírgula (ex.: localhost:50053,localhost:50054)")
    parser.add_argument("--active", action="store_true", help="iniciar workload automático")
    args = parser.parse_args()

    my_addr = f"[::]:{args.port}"
    peers = [c.strip() for c in args.clients.split(",") if c.strip()]

    client = RAClient(client_id=args.id, my_addr=my_addr, peers=peers, printer_addr=args.server)
    client.start_server()

    # Thread do workload (opcional; pode ligar com --active)
    if args.active:
        t = threading.Thread(target=client.run_workload, daemon=True)
        t.start()

    client.wait_server()


if __name__ == "__main__":
    main()
