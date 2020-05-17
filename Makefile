default: python

python:
	python -m grpc_tools.protoc -I./proto -I../moca-proto --python_out=. --purerpc_out=. ./proto/*.proto ../moca-proto/*.proto

all: python

clean:
	rm -rf *_pb2.py
	rm -rf *_pb2_grpc.py

watch:
	@echo "Waiting for file changes..."
	@while true; do \
		make $(WATCHMAKE); \
		inotifywait -qre close_write .; \
	done
