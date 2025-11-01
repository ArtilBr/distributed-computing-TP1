import time
import random
from concurrent import futures

import grpc
import distributed_printing_pb2 as pb2
import distributed_printing_pb2_grpc as pb2_grpc


class PrintingService(pb2_grpc.PrintingServiceServicer):
    def SendToPrinter(self, request, context):
        # Simula impressão (2–3s)
        delay = random.uniform(2.0, 3.0)
        ts = request.lamport_timestamp
        print(f"[TS: {ts}] CLIENTE {request.client_id}: {request.message_content} (req #{request.request_number})")
        time.sleep(delay)
        return pb2.PrintResponse(
            success=True,
            confirmation_message=f"Impresso com sucesso em {delay:.2f}s",
            lamport_timestamp=ts
        )


def serve(host="0.0.0.0", port=50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    pb2_grpc.add_PrintingServiceServicer_to_server(PrintingService(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    print(f"Servidor de impressão burro rodando em {host}:{port}")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == "__main__":
    serve()
