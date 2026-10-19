Shader "Xnu/FieldFallbackUnlit"
{
    // Ersatz für die Originalshader der Feldkarten (Switch-Binärcode, nicht renderbar) bis zum Shader-Port.
    // Unlit mit Haupttextur, Farbe und optionalem Alpha-Test; keine Beleuchtung, kein Nachbau des Originallooks.
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _Color ("Color", Color) = (1,1,1,1)
        _Cutoff ("Alpha Cutoff", Range(0,1)) = 0
    }
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry" }
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float4 _MainTex_ST;
            fixed4 _Color;
            fixed _Cutoff;

            struct appdata { float4 vertex : POSITION; float2 uv : TEXCOORD0; };
            struct v2f { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };

            v2f vert(appdata v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv = TRANSFORM_TEX(v.uv, _MainTex);
                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                fixed4 c = tex2D(_MainTex, i.uv) * _Color;
                if (_Cutoff > 0) clip(c.a - _Cutoff);
                return fixed4(c.rgb, 1);
            }
            ENDCG
        }
    }
    Fallback Off
}
