# printer_server.py
import time
import random 
from concurrent import futures
import grpc

from protocol import printing_pb2
from protocol import printing_pb2_grpc

class PrintingServiceServicer(printing_pb2_grpc.PrintingServiceServicer):
    def SendToPrinter(self, request, context):
        # A impressão 
        print(f"[TS: {request.lamport_timestamp}] CLIENTE {request.client_id}: {request.message_content}")
        
        # Simula tempo de impressão 
        time.sleep(random.uniform(2, 3))
        
        # Cria a resposta
        resp = printing_pb2.PrintResponse(
            success=True,
            confirmation_message=f"Impressão concluída para cliente {request.client_id}",
            # Ecoa o timestamp do cliente 
            lamport_timestamp=request.lamport_timestamp 
        )
        return resp

def serve(port=50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    printing_pb2_grpc.add_PrintingServiceServicer_to_server(PrintingServiceServicer(), server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    print(f"✅ Printer server rodando na porta :{port}")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("Printer server encerrado.")

if __name__ == "__main__":
    serve()