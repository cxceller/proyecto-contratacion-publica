# TinyMCE vendorizado

- **Version:** 6.8.3 (Community, LGPL-2.0-or-later; ver `tinymce/license.txt`)
- **Origen:** paquete npm `tinymce@6.8.3` (https://registry.npmjs.org/tinymce/-/tinymce-6.8.3.tgz).
- **Verificacion:** el `sha512` del tarball coincide con `dist.integrity` del registro npm, y el `sha512` de
  `tinymce.min.js` coincide con el SRI publicado por cdnjs para 6.8.3 (dos fuentes independientes).
- **Por que:** antes se cargaba desde cdnjs sin SRI (cadena de suministro) y exigia internet; ahora es local.
- **Solo** se incluyen los archivos que usa el editor (plugins `table image lists link`, tema silver, skin oxide).
- **Actualizar:** descargar la nueva version, verificar su integridad igual que arriba y reemplazar estos archivos.

| Archivo | SHA-256 |
|---|---|
| `tinymce.min.js` | `51f0b1464c0cea3c9a52d58631d4d31847445e6309a3515f08a41e9090528072` |
| `license.txt` | `55cc2df5c872aa8f94bb8d05839e736003069d84317bda2e4ada4c03b604871a` |
| `themes/silver/theme.min.js` | `84abe51fec7b1eae9c2a305ed363d736014dec31919eb03bf0f229e34122d154` |
| `models/dom/model.min.js` | `2014140264f521e64b0bdd63fedec898ee40fed807ad1519bceaaa2849b98816` |
| `icons/default/icons.min.js` | `df42e91e6e15da0ab50513280cba33c8fb6d4e0fbdb4d8edaf3d39209d8d6d18` |
| `plugins/table/plugin.min.js` | `6cb44d87a728f673521491340bb51e53d44566a9c443fc50d4b764c55672a3be` |
| `plugins/image/plugin.min.js` | `ca68b019981d45840d6d625582b1e6100a34e32fdf675d330af1c37be4a63e0a` |
| `plugins/lists/plugin.min.js` | `8b08e7625bbfd377f9c2eba8574aab0f074749a63345d292d4463b743215be12` |
| `plugins/link/plugin.min.js` | `84663a65ea54475e8d23062a1aac3f817fbf183021c9f011556d23313a103633` |
| `skins/ui/oxide/skin.min.css` | `e9e58eb82c861c267cfe55314bfab35e7773d812d0824c8509671343aad61a43` |
| `skins/ui/oxide/content.min.css` | `d8ed2dc2506a1aad13dd2c56e7a041348f322ba07d4230330d04834c843df2b5` |
| `skins/content/default/content.min.css` | `245f475b07f8bd8b85aaae5bd67077a237bf85e53185736bb1bc2092aca2b33a` |
