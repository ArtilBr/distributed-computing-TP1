import time
import argparse
import grpc
from concurrent import futures

import printing_pb2
import printing_pb2_grpc


class PrintingServiceImpl(printing_pb2_grpc.PrintingServiceServicer):
    def SendToPrinter(self, request, context):
        # Simula impressão
        print(f"[TS: {request.lamport_timestamp}] CLIENTE {request.client_id} (req #{request.request_number}): {request.message_content}")
        time.sleep(2.0)  # delay de impressão
        return printing_pb2.PrintResponse(
            success=True,
            confirmation_message=f"Impresso (cliente {request.client_id}, req {request.request_number})",
            lamport_timestamp=int(time.time())  # timestamp “real” só como informação
        )


def serve(port: int):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    printing_pb2_grpc.add_PrintingServiceServicer_to_server(PrintingServiceImpl(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"[Printer] Servidor burro iniciado na porta {port}")
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=50051)
    args = parser.parse_args()
    serve(args.port)
