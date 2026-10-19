using UnityEngine;
using UnityEngine.Rendering;

namespace Xnu.Render
{
    // Port von ReflectionCameraFollower (docs/shader-globals.md, Abschnitt 4): Reflexionskamera, an der Ebene y = 0 gespiegelt,
    // rendert in eine Textur (Bildschirmgröße, Tiefe 24, Mips). Globals: _ReflectionTex (Textur) und
    // _ReflectionVP (GPU-Projektion · Welt→Kamera der Reflexionskamera). Die Kamera liegt auf demselben Objekt.
    [RequireComponent(typeof(Camera))]
    public sealed class ReflectionCameraDriver : MonoBehaviour
    {
        public Camera Target;             // Hauptkamera
        public float FovScale = 1f;       // _fovScale
        public int CustomWidth, CustomHeight;   // SetCustomResolution; <= 0: Bildschirmgröße

        Camera _camera;
        RenderTexture _rt;
        int _texId, _vpId;

        void OnEnable()
        {
            _camera = GetComponent<Camera>();
            _texId = Shader.PropertyToID("_ReflectionTex");
            _vpId = Shader.PropertyToID("_ReflectionVP");
            EnsureTexture();
        }

        void OnDisable()
        {
            if (_camera != null) _camera.targetTexture = null;
            if (_rt != null) DestroyImmediate(_rt);
            _rt = null;
        }

        void EnsureTexture()
        {
            var w = CustomWidth > 0 ? CustomWidth : Screen.width;
            var h = CustomHeight > 0 ? CustomHeight : Screen.height;
            if (w <= 0 || h <= 0) return;
            if (_rt != null && (_rt.width != w || _rt.height != h))
            {
                _camera.targetTexture = null;
                DestroyImmediate(_rt);
                _rt = null;
            }
            if (_rt == null)
            {
                _rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32) { useMipMap = true, autoGenerateMips = true };
                _camera.targetTexture = _rt;
            }
        }

        void LateUpdate()
        {
            if (Target == null || _camera == null) return;
            EnsureTexture();
            if (_camera.targetTexture == null) return;
            var tt = Target.transform;
            var p = tt.position;
            var e = tt.rotation.eulerAngles;
            transform.position = new Vector3(p.x, -p.y, p.z);
            transform.rotation = Quaternion.Euler(-e.x, e.y, -e.z);
            _camera.fieldOfView = Target.fieldOfView * FovScale;
            var vp = GL.GetGPUProjectionMatrix(_camera.projectionMatrix, false) * _camera.worldToCameraMatrix;
            Shader.SetGlobalMatrix(_vpId, vp);
            Shader.SetGlobalTexture(_texId, _camera.targetTexture);
        }
    }

    // Entsprechung von MultipleCameraCompositor für die Tiefentexturen der Shader (Built-in-Pipeline):
    //  _OpaqueDepthTexture = Tiefe nach dem undurchsichtigen Forward-Durchgang (CameraEvent.AfterForwardOpaque),
    //  _GlobalDepthTexture = Tiefe der gemeinsamen Zieltextur (CameraEvent.BeforeForwardOpaque im Original); mit einer einzigen
    //  Kamera ist das dieselbe Tiefentextur (_CameraDepthTexture). Mehrere Ebenenkameras brauchen den Ausbau mit gemeinsamer Zieltextur.
    [RequireComponent(typeof(Camera))]
    public sealed class DepthCaptureDriver : MonoBehaviour
    {
        CommandBuffer _opaque, _global;
        Camera _camera;

        void OnEnable()
        {
            _camera = GetComponent<Camera>();
            _camera.depthTextureMode |= DepthTextureMode.Depth;
            _opaque = new CommandBuffer { name = "XNU OpaqueDepth" };
            _opaque.SetGlobalTexture("_OpaqueDepthTexture", BuiltinRenderTextureType.Depth);
            _camera.AddCommandBuffer(CameraEvent.AfterForwardOpaque, _opaque);
            _global = new CommandBuffer { name = "XNU GlobalDepth" };
            _global.SetGlobalTexture("_GlobalDepthTexture", BuiltinRenderTextureType.Depth);
            _camera.AddCommandBuffer(CameraEvent.BeforeForwardOpaque, _global);
        }

        void OnDisable()
        {
            if (_camera == null) return;
            if (_opaque != null) { _camera.RemoveCommandBuffer(CameraEvent.AfterForwardOpaque, _opaque); _opaque.Release(); }
            if (_global != null) { _camera.RemoveCommandBuffer(CameraEvent.BeforeForwardOpaque, _global); _global.Release(); }
            _opaque = _global = null;
        }
    }
}
