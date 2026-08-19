FROM python:3.10-slim

WORKDIR /app

COPY packages/ /app/packages/

COPY requirements.txt .

COPY api_server.py config.py power_agent.py grid_tools.py llm_client.py example_usage.py verify_new_tools.py verify_test_examples.py /app/

COPY web/ /app/web/

RUN pip install --no-index --find-links=/app/packages/ \
    pandapower==3.4.0 \
    pandas>=2.0.0 \
    numpy>=1.24.0 \
    requests>=2.28.0

EXPOSE 8000

CMD ["python", "api_server.py", "--host", "0.0.0.0", "--port", "8000"]