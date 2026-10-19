using System;
using Xnu.Data;

namespace Xnu.Field
{
    // Attributraster einer Karte: Matrix aus 32 x 32 großen Blöcken (AttributeMatrix + AttributeBlock).
    // Zugriff wie GameManager.GetAttribute: Block (gx >> 5, gy >> 5), darin (gx & 31, gy & 31).
    public sealed class AttributeLayer
    {
        readonly int _matrixWidth;
        readonly int _matrixHeight;
        readonly int[][] _blocks;   // null = kein Block an dieser Stelle

        public string Name { get; }
        public int BlockColumns => _matrixWidth;
        public int BlockRows => _matrixHeight;

        // blockLookup liefert einen Block anhand seines Namens (null, wenn unbekannt).
        public AttributeLayer(AttributeMatrixRecord matrix, Func<string, AttributeBlockRecord> blockLookup)
        {
            if (matrix == null) throw new ArgumentNullException(nameof(matrix));
            if (blockLookup == null) throw new ArgumentNullException(nameof(blockLookup));
            Name = matrix.Name;
            _matrixWidth = matrix.Width;
            if (_matrixWidth <= 0) throw new ArgumentException("Matrixbreite muss positiv sein", nameof(matrix));
            _matrixHeight = (matrix.BlockNames.Length + _matrixWidth - 1) / _matrixWidth;
            _blocks = new int[matrix.BlockNames.Length][];
            for (var i = 0; i < _blocks.Length; i++)
            {
                var n = matrix.BlockNames[i];
                if (string.IsNullOrEmpty(n)) continue;
                var b = blockLookup(n);
                if (b == null) continue;
                if (b.Width != FieldCoords.BlockSize) throw new ArgumentException("Block " + n + " hat Breite " + b.Width + " statt 32");
                _blocks[i] = b.Attributes;
            }
        }

        // Rohwerte direkt (für Tests und synthetische Karten): ein Block je Eintrag, 32 x 32 Werte.
        public AttributeLayer(string name, int matrixWidth, int[][] blocks)
        {
            Name = name ?? "";
            _matrixWidth = matrixWidth;
            _blocks = blocks ?? throw new ArgumentNullException(nameof(blocks));
            _matrixHeight = (blocks.Length + matrixWidth - 1) / matrixWidth;
        }

        public bool HasBlockAt(int gx, int gy)
        {
            if (gx < 0 || gy < 0) return false;
            var col = gx >> 5;
            var row = gy >> 5;
            if (col >= _matrixWidth) return false;
            var idx = row * _matrixWidth + col;
            return idx < _blocks.Length && _blocks[idx] != null;
        }

        // Rohwert; außerhalb der Matrix oder ohne Block 0 (wie im Original, dort ist das begehbar).
        public int GetRaw(int gx, int gy)
        {
            if (gx < 0 || gy < 0) return 0;
            var col = gx >> 5;
            var row = gy >> 5;
            if (col >= _matrixWidth) return 0;
            var idx = row * _matrixWidth + col;
            if (idx >= _blocks.Length) return 0;
            var block = _blocks[idx];
            if (block == null) return 0;
            var i = (gy & 31) * FieldCoords.BlockSize + (gx & 31);
            return i < block.Length ? block[i] : 0;
        }

        public AttributeCell Get(int gx, int gy) => AttributeCell.Decode(GetRaw(gx, gy));
    }
}
