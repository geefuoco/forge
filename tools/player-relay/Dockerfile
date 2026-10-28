FROM python:3.13-alpine
WORKDIR /relay
COPY --chmod=0444 server.py /relay/server.py
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["python3", "-B", "/relay/server.py", "--host", "0.0.0.0", "--port", "8080"]
