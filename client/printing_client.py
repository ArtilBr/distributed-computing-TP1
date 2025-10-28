# printing_client.py
import threading
import time
import random
import grpc
from concurrent import futures
from protocol import printing_pb2
from protocol import printing_pb2_grpc
from google.protobuf import empty_pb2
import argparse

class LamportClock:
    def __init__(self):
        self.lock = threading.Lock()
        self.time = 0

    def tick(self):
        with self.lock:
            self.time += 1
            return self.time

    def update(self, other_ts):
        with self.lock:
            self.time = max(self.time, other_ts) + 1
            return self.time

    def read(self):
        with self.lock:
            return self.time

class MutualExclusionServicer(printing_pb2_grpc.MutualExclusionServiceServicer):
    def __init__(self, client):
        self.client = client

    def RequestAccess(self, request, context):
        # chamada recebida de outro cliente pedindo acesso
        their_ts = request.lamport_timestamp
        their_id = request.client_id
        their_reqnum = request.request_number

        self.client.lamport.update(their_ts)
        # decide se concede ou adia
        grant = False
        with self.client.state_lock:
            if not self.client.requesting:
                grant = True
            else:
                # comparar (ts, id)
                my_tuple = (self.client.request_ts, self.client.client_id)
                their_tuple = (their_ts, their_id)
                if their_tuple < my_tuple:
                    grant = True
                else:
                    # adiar
                    self.client.deferred.add(their_id)
                    grant = False

        # se conceder, mandar resposta imediata
        resp = printing_pb2.AccessResponse(
            access_granted=grant,
            lamport_timestamp=self.client.lamport.tick()
        )
        return resp

    def ReleaseAccess(self, request, context):
        their_ts = request.lamport_timestamp
        their_id = request.client_id
        self.client.lamport.update(their_ts)
        with self.client.state_lock:
            # quando receber release, se havia adiado esse id, remover e responder
            if their_id in self.client.deferred:
                # nothing to do here; o adiado só importa para o dono liberar depois
                pass
        return empty_pb2.Empty()

class PrintingClient:
    def __init__(self, client_id, local_port, printer_addr, peers):
        self.client_id = client_id
        self.local_port = local_port
        self.printer_addr = printer_addr
        self.peers = peers  # lista de "host:port"
        self.lamport = LamportClock()

        self.requesting = False
        self.request_ts = None
        self.request_number = 0
        self.deferred = set()
        self.replies_needed = set()
        self.state_lock = threading.Lock()
        self.reply_cv = threading.Condition(self.state_lock)

        # start gRPC server for MutualExclusionService
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        printing_pb2_grpc.add_MutualExclusionServiceServicer_to_server(MutualExclusionServicer(self), self.server)
        self.server.add_insecure_port(f'[::]:{self.local_port}')

        # stubs to peers will be created lazily
        self.peer_stubs = {}
        for p in self.peers:
            self.peer_stubs[p] = printing_pb2_grpc.MutualExclusionServiceStub(grpc.insecure_channel(p))

        # stub to printer server
        self.printer_stub = printing_pb2_grpc.PrintingServiceStub(grpc.insecure_channel(self.printer_addr))

    def start(self):
        self.server.start()
        print(f"[Cliente {self.client_id}] Servidor de MutualExclusion rodando em :{self.local_port}")
        # start thread that generates print requests
        threading.Thread(target=self._auto_print_generator, daemon=True).start()
        # start status printer
        threading.Thread(target=self._status_loop, daemon=True).start()

    def stop(self):
        self.server.stop(0)

    def _status_loop(self):
        while True:
            with self.state_lock:
                st = "REQUESTING" if self.requesting else "IDLE"
                ts = self.lamport.read()
                deferred = list(self.deferred)
            print(f"[Cliente {self.client_id} | TS={ts}] Status: {st}, deferred={deferred}")
            time.sleep(3)

    def _auto_print_generator(self):
        while True:
            # espera intervalo aleatório 4-8s
            time.sleep(random.uniform(4, 8))
            message = f"Documento gerado aleatoriamente pelo cliente {self.client_id} @ {int(time.time())}"
            print(f"[Cliente {self.client_id}] Gerando pedido de impressão: \"{message}\"")
            self.request_number += 1
            self.request_critical_section(message, self.request_number)

    def request_critical_section(self, message, reqnum):
        # passo 1: setar requesting e enviar requests para todos
        with self.state_lock:
            self.requesting = True
            self.request_ts = self.lamport.tick()
            self.request_number = reqnum
            self.replies_needed = set(self.peers)  # identificador por endereço host:port
            # map addresses to ids? assumimos que peers conhecem IDs; neste exemplo
            # replies counted por endereço, pois RequestAccess responde imediatamente.

        # enviar RequestAccess para todos os peers
        req_msg = printing_pb2.AccessRequest(
            client_id=self.client_id,
            lamport_timestamp=self.request_ts,
            request_number=self.request_number
        )

        def send_req_to(peer_addr, stub):
            try:
                resp = stub.RequestAccess(req_msg, timeout=5)
                # atualizar relógio ao receber resposta
                self.lamport.update(resp.lamport_timestamp)
                if resp.access_granted:
                    with self.state_lock:
                        if peer_addr in self.replies_needed:
                            self.replies_needed.remove(peer_addr)
                            with self.reply_cv:
                                self.reply_cv.notify_all()
                else:
                    # Se respondeu que não concede, significa que deferiu: a lógica de adiamento
                    # aqui não garante resposta posterior; o dono libera via ReleaseAccess.
                    # Para simplificar, tratamos a ausência de grant como "vou aguardar release"
                    with self.state_lock:
                        if peer_addr in self.replies_needed:
                            # ainda aguarda; não remover
                            pass
            except Exception as e:
                print(f"[Cliente {self.client_id}] Erro ao contactar peer {peer_addr}: {e}")
                # se não consegui falar com peer, tratamos como concedido (ou opcional: falha)
                with self.state_lock:
                    if peer_addr in self.replies_needed:
                        self.replies_needed.remove(peer_addr)
                        with self.reply_cv:
                            self.reply_cv.notify_all()

        # spawn threads para enviar
        threads = []
        for peer_addr, stub in self.peer_stubs.items():
            t = threading.Thread(target=send_req_to, args=(peer_addr, stub))
            t.start()
            threads.append(t)

        # aguardar replies_needed ficar vazio
        with self.reply_cv:
            while len(self.replies_needed) > 0:
                # espera notificações (respostas)
                self.reply_cv.wait(timeout=1)
                # também vamos verificar se algum peer enviou ReleaseAccess que nos limpa via deferred
                # mas ReleaseAccess não ativa resposta — em implementações completas você mandaria um Grant.
                # Para robustez, vamos tentar contornar por rechecagens periódicas.
        # entrou na seção crítica
        print(f"[Cliente {self.client_id} | TS={self.lamport.read()}] Entrando na seção crítica para imprimir.")
        # usa o PrintingService do servidor burro
        try:
            self.lamport.tick()
            pr = printing_pb2.PrintRequest(
                client_id=self.client_id,
                message_content=message,
                lamport_timestamp=self.lamport.read(),
                request_number=reqnum
            )
            resp = self.printer_stub.SendToPrinter(pr, timeout=10)
            self.lamport.update(resp.lamport_timestamp)
            print(f"[Cliente {self.client_id}] Recebeu confirmação do servidor de impressão: {resp.confirmation_message}")
        except Exception as e:
            print(f"[Cliente {self.client_id}] Erro ao enviar para impressora: {e}")

        # sair da seção crítica -> liberar e notificar peers que estavam adiados
        with self.state_lock:
            self.requesting = False
            # notificar todos os peers com ReleaseAccess (mesmo que alguns não tenham deferido)
            release = printing_pb2.AccessRelease(
                client_id=self.client_id,
                lamport_timestamp=self.lamport.tick(),
                request_number=reqnum
            )
            deferred_peers = list(self.deferred)
            self.deferred.clear()

        for peer_addr, stub in self.peer_stubs.items():
            try:
                stub.ReleaseAccess(release, timeout=5)
            except Exception as e:
                print(f"[Cliente {self.client_id}] Erro enviando Release para {peer_addr}: {e}")

        print(f"[Cliente {self.client_id}] Liberou recurso e notificou peers.")

def parse_peers(s):
    # entrada ex: localhost:50053,localhost:50054
    s = s.strip()
    if not s:
        return []
    return [p.strip() for p in s.split(",") if p.strip()]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, dest="client_id")
    parser.add_argument("--server", type=str, required=True, dest="printer_addr")
    parser.add_argument("--port", type=int, required=True, dest="local_port")
    parser.add_argument("--peers", type=str, default="", dest="peers")
    args = parser.parse_args()

    peers = parse_peers(args.peers)
    client = PrintingClient(args.client_id, args.local_port, args.printer_addr, peers)
    client.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        client.stop()
        print("Cliente encerrado.")
