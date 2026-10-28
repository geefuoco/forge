# syntax=docker/dockerfile:1
FROM maven:3.9.9-eclipse-temurin-21 AS build
RUN --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then cp /run/secrets/proxy_ca /usr/local/share/ca-certificates/build-proxy.crt; update-ca-certificates; fi; \
    apt-get update && apt-get install -y --no-install-recommends python3 git && rm -rf /var/lib/apt/lists/* && \
    rm -f /usr/local/share/ca-certificates/build-proxy.crt && update-ca-certificates --fresh
WORKDIR /source
COPY . .
ARG SOURCE_REVISION
RUN git init && python3 -c 'import pathlib,re,sys; revision=sys.argv[1]; assert re.fullmatch("[0-9a-f]{40}", revision), "SOURCE_REVISION must be the source git commit"; pathlib.Path(".git/HEAD").write_text(revision + "\n")' "$SOURCE_REVISION"
RUN --mount=type=secret,id=proxy_ca \
    python3 tools/hosted-engine/maven-settings.py /tmp/hosted-settings.xml && \
    if [ -s /run/secrets/proxy_ca ]; then keytool -importcert -noprompt -cacerts -storepass changeit -alias build-proxy -file /run/secrets/proxy_ca; fi && \
    mvn -s /tmp/hosted-settings.xml -B -pl forge-gui-desktop -am -DskipTests compile dependency:build-classpath -DincludeScope=runtime -Dmdep.outputFile=target/hosted-classpath.txt && \
    rm /tmp/hosted-settings.xml && \
    if [ -s /run/secrets/proxy_ca ]; then keytool -delete -cacerts -storepass changeit -alias build-proxy; fi
RUN python3 tools/hosted-engine/prepare.py --classpath-file forge-gui-desktop/target/hosted-classpath.txt --output /bundle
RUN python3 web/neoforge/tools/generate-catalog.py --forge-root /source

FROM eclipse-temurin:21-jre-jammy AS runtime
RUN --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then cp /run/secrets/proxy_ca /usr/local/share/ca-certificates/build-proxy.crt; update-ca-certificates; fi; \
    apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/* && \
    rm -f /usr/local/share/ca-certificates/build-proxy.crt && update-ca-certificates --fresh && \
    useradd --uid 10001 --create-home neoforge
WORKDIR /opt/neoforge
COPY --from=build /bundle/runtime ./runtime
COPY --from=build /source/forge-gui/res ./forge-gui/res
COPY --from=build /source/forge-gui-desktop/pom.xml ./forge-gui-desktop/pom.xml
COPY --from=build /source/tools/hosted-engine/server.py ./tools/hosted-engine/server.py
COPY --from=build /source/web/neoforge/dist ./web/neoforge/dist
ENV FORGE_BRIDGE_CLASSES=/opt/neoforge/runtime/bridge PORT=8080 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["sh", "-c", "export FORGE_BRIDGE_CLASSPATH=\"$(cat /opt/neoforge/runtime/classpath.txt)\"; exec python3 /opt/neoforge/tools/hosted-engine/server.py --host 0.0.0.0 --port \"${PORT}\" --origin \"${NEOFORGE_ORIGIN:?Set NEOFORGE_ORIGIN to the public HTTPS origin}\" \"$@\"", "neoforge"]
CMD ["--max-workers", "2", "--heap", "1024m"]
