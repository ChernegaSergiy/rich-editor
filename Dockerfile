FROM python:3.12-alpine
WORKDIR /srv
COPY app ./app
ENV DATA_DIR=/data PORT=8080
EXPOSE 8080
CMD ["python3", "app/backend.py"]
