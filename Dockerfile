FROM python:3.11-slim

WORKDIR /app

COPY table_parser.py .
COPY validate_result.py .
COPY input_data ./input_data

RUN mkdir -p results

CMD ["sh", "-c", "python table_parser.py && python validate_result.py"]