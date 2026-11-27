FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf
RUN apk add --no-cache ca-certificates python3 py3-botocore postgresql18-client
WORKDIR /opt/vidra-native
COPY origin.py prepare.py ./
COPY runtime/native/run-native.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/opt/vidra-native/run-native.py"]
