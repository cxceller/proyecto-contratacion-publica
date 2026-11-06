// Logica del componente TinyMCE (antes inline en index.html). Externalizado para poder servir la app
// con una CSP sin 'unsafe-inline' en script-src.
(function () {
  "use strict";

  // Protocolo crudo de Streamlit Components (sin streamlit-component-lib
  // ni build de Node): ver "Create a Component" > "Static HTML" en la
  // documentacion de Streamlit. Es solo postMessage en ambas direcciones.
  // OJO: el mensaje "streamlit:render" que Streamlit envia AL componente
  // NO trae el campo isStreamlitMessage -- ese wrapper solo aplica a los
  // mensajes que el COMPONENTE envia hacia Streamlit (setComponentValue,
  // setFrameHeight, componentReady). Exigirlo tambien al recibir hacia
  // que el render se descartara en silencio y tinymce.init() nunca se
  // llamara.
  function enviarAlPadre(tipo, extra) {
    var payload = Object.assign({ isStreamlitMessage: true, type: tipo }, extra || {});
    window.parent.postMessage(payload, "*");
  }

  function fijarAltoFrame(alto) {
    enviarAlPadre("streamlit:setFrameHeight", { height: alto });
  }

  var ultimoValorEnviado = null;
  function enviarValorActual(valor) {
    if (valor === ultimoValorEnviado) return;
    ultimoValorEnviado = valor;
    enviarAlPadre("streamlit:setComponentValue", { value: valor });
  }

  var editorListo = false;
  var tinymceInitLlamado = false;
  var alturaActual = 400;
  var contenidoInicialPendiente = "";

  function inicializarEditor(valorInicial, alto) {
    alturaActual = alto || 400;
    contenidoInicialPendiente = valorInicial || "";
    if (editorListo || tinymceInitLlamado) {
      // El iframe ya tiene un editor montado, o ya se disparo
      // tinymce.init() y su callback "init" (asincrono) todavia no
      // resolvio -- Streamlit puede mandar varios "streamlit:render"
      // seguidos antes de que ese callback llegue, y llamar a
      // tinymce.init() mas de una vez sobre el mismo selector lo deja en
      // un estado inconsistente. Tampoco se reinicializa una vez montado,
      // para no perder el cursor/seleccion del usuario a mitad de edicion.
      return;
    }
    tinymceInitLlamado = true;
    tinymce.init({
      selector: "#editor",
      height: alturaActual,
      menubar: false,
      branding: false,
      // "paste" ya no es un plugin separado desde TinyMCE 6 (el pegado,
      // incluido paste_data_images, paso a ser parte del core) -- listarlo
      // aqui solo generaba un 404 al intentar cargar un archivo que ya no
      // existe en esta version.
      plugins: "table image lists link",
      toolbar:
        "undo redo | bold italic underline | bullist numlist | " +
        "table image link | removeformat",
      paste_data_images: true,
      paste_as_text: false,
      table_toolbar:
        "tableprops tabledelete | tableinsertrowbefore tableinsertrowafter " +
        "tabledeleterow | tableinsertcolbefore tableinsertcolafter tabledeletecol",
      setup: function (editor) {
        editor.on("init", function () {
          editor.setContent(contenidoInicialPendiente);
          editorListo = true;
          fijarAltoFrame(alturaActual + 20);
          enviarValorActual(editor.getContent());
        });
        editor.on("change keyup blur SetContent", function () {
          enviarValorActual(editor.getContent());
        });
      },
    });
  }

  window.addEventListener("message", function (event) {
    var datos = event.data;
    if (!datos || datos.type !== "streamlit:render") return;
    var args = datos.args || {};
    inicializarEditor(args.value, args.height);
  });

  enviarAlPadre("streamlit:componentReady", { apiVersion: 1 });
  fijarAltoFrame(alturaActual);
})();
