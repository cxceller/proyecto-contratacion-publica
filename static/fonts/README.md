# Fuentes vendorizadas

- **IBM Plex Sans** (subconjunto `latin`: cubre español: ñ, tildes, ¿ ¡, guiones y puntuación), pesos 400/500/600/700.
- **Licencia:** SIL Open Font License 1.1 (ver `ibm-plex-sans/LICENSE.txt`).
- **Origen:** paquete npm `@fontsource/ibm-plex-sans@5.3.0`; el `sha512` del tarball coincide con `dist.integrity` del registro.
- **Por qué:** antes la app cargaba Inter desde Google Fonts (peticion externa, dato de IP a un tercero y dependencia de red);
  ahora todo sale del propio servidor (`server.enableStaticServing`, URL `/app/static/fonts/...`) y la CSP no necesita
  `fonts.googleapis.com` ni `fonts.gstatic.com`.
- **Actualizar:** descargar la nueva version, verificar su integridad y reemplazar estos archivos.

| Archivo | SHA-256 | Tamano |
|---|---|---|
| `ibm-plex-sans-latin-400-normal.woff2` | `3b646991d30055a93a4ecc499713d4347953a74a947ecab435ab72070cbdab0e` | 22 KB |
| `ibm-plex-sans-latin-500-normal.woff2` | `0717336fb31fcdcde4b8deb3675bb4a0f7f6d484864afcd6751ac29975962203` | 23 KB |
| `ibm-plex-sans-latin-600-normal.woff2` | `8960851d691c054ed38e259bdcf1a6190d157b4203ed5bb32c632a863fb8ec2f` | 23 KB |
| `ibm-plex-sans-latin-700-normal.woff2` | `42e7b0c143c19df9d99fd896e76b48f846edf0902d200bc29796b34d12c33aa7` | 22 KB |
