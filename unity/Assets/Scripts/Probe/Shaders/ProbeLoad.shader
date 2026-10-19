// Eigener Lastshader der Mess-App (nur Rechenlast, keine Spielinhalte).
Shader "Xnu/ProbeLoad"
{
    Properties
    {
        _Iter ("Iterationen", Float) = 64
    }
    SubShader
    {
        Pass
        {
            ZTest Always
            Cull Off
            ZWrite Off

            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            float _Iter;

            struct v2f
            {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
            };

            v2f vert(appdata_img v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv = v.texcoord;
                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                float2 p = i.uv;
                float a = 0;
                int n = (int)_Iter;
                for (int k = 0; k < n; k++)
                {
                    p = frac(sin(p * 12.9898 + k) * 43758.5453);
                    a += p.x * p.y;
                }
                return fixed4(frac(a), p.x, p.y, 1);
            }
            ENDCG
        }
    }
}
