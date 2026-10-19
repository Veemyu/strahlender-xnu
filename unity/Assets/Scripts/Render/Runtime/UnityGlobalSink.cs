using UnityEngine;

namespace Xnu.Render
{
    // Setzt die Spiel-Globals über Shader.SetGlobal*.
    public sealed class UnityGlobalSink : IGlobalSink
    {
        public void SetFloat(string name, float value) => Shader.SetGlobalFloat(name, value);

        public void SetVector(string name, float x, float y, float z, float w) => Shader.SetGlobalVector(name, new Vector4(x, y, z, w));

        public void SetMatrix(string name, float[] m)
        {
            var mat = new Matrix4x4();
            for (var i = 0; i < 16; i++) mat[i / 4, i % 4] = m[i];
            Shader.SetGlobalMatrix(name, mat);
        }

        public void SetTexture(string name, object texture) => Shader.SetGlobalTexture(name, (Texture)texture);
    }
}
