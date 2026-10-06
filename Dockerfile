FROM node:22-alpine AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend ./frontend
COPY app ./app
RUN cd frontend && npm run build

FROM python:3.12-alpine
WORKDIR /srv
COPY app ./app
COPY --from=web /src/app/static/dist ./app/static/dist
ENV DATA_DIR=/data PORT=8080
EXPOSE 8080
CMD ["python3", "app/backend.py"]
