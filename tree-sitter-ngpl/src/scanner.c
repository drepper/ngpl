// The layout NGPL is written in, and the two forms of string literal.
//
// A block is opened by indentation, so the newline that ends a
// statement and the indent that opens a block are tokens the grammar
// asks for by name.  Two things put them away again, and both fall out
// of what the parser can accept where it stands: a line inside
// brackets, and a line whose last token is an operator still waiting
// for its right-hand side.  In neither case is a newline something the
// grammar can use, so the scanner is not asked for one, and the line
// break passes as whitespace -- which is what the compiler's own lexer
// does by counting brackets, and its interpreter by looking back at
// the last token on the line.
//
// Strings are scanned here rather than by a pattern because the
// multi-line form ends at the first three quotes and holds single ones
// freely, which is easier to say as a loop than as a regular
// expression.

#include "tree_sitter/parser.h"

#include <stdlib.h>
#include <string.h>

enum TokenType {
  NEWLINE,
  INDENT,
  DEDENT,
  STRING,
  ERROR_SENTINEL,
};

#define MAX_DEPTH 128

typedef struct {
  // the indentation of every block still open, the outermost first
  uint16_t indents[MAX_DEPTH];
  uint8_t depth;
  // the indentation of the line just reached, while the blocks it
  // opens or closes are still being handed over; -1 when there is none
  int32_t pending;
  // whether the newline that ends the last statement of the file has
  // been handed over: the end of a file is a place the scanner is
  // asked about again and again, and it has only the one to give
  bool eof_newline;
} Scanner;

static void skip(TSLexer *lexer) { lexer->advance(lexer, true); }
static void advance(TSLexer *lexer) { lexer->advance(lexer, false); }

// A string literal.  One quote opens a string that ends on the line it
// began; three open one that ends at the next three, so a single quote
// inside such a string stands for itself.
static bool scan_string(TSLexer *lexer) {
  advance(lexer);                       // the quote that opened it
  bool multi = false;
  if (lexer->lookahead == '"') {
    advance(lexer);
    if (lexer->lookahead != '"') {      // "" -- the empty string
      lexer->result_symbol = STRING;
      return true;
    }
    advance(lexer);
    multi = true;
  }

  unsigned quotes = 0;                  // how many in a row, for the close
  for (;;) {
    if (lexer->eof(lexer)) return false;
    if (lexer->lookahead == '\\') {
      advance(lexer);
      if (lexer->eof(lexer)) return false;
      advance(lexer);
      quotes = 0;
      continue;
    }
    if (lexer->lookahead == '"') {
      advance(lexer);
      if (!multi) {
        lexer->result_symbol = STRING;
        return true;
      }
      if (++quotes == 3) {
        lexer->result_symbol = STRING;
        return true;
      }
      continue;
    }
    if (lexer->lookahead == '\n' && !multi) return false;
    advance(lexer);
    quotes = 0;
  }
}

// Whitespace, and the comments that are whitespace with something
// written in them.  Answers whether a line ended along the way, and
// leaves the indentation of the line reached in *indent.
static bool skip_gaps(TSLexer *lexer, uint16_t *indent) {
  bool ended = false;
  *indent = 0;
  for (;;) {
    if (lexer->lookahead == ' ') {
      *indent += 1;
      skip(lexer);
    } else if (lexer->lookahead == '\t') {
      // the compiler reads spaces only; counting one keeps the scanner
      // moving so that the refusal comes from the compiler, not a hang
      *indent += 1;
      skip(lexer);
    } else if (lexer->lookahead == '\r') {
      skip(lexer);
    } else if (lexer->lookahead == '\n') {
      ended = true;
      *indent = 0;
      skip(lexer);
    } else if (lexer->lookahead == '/') {
      skip(lexer);
      if (lexer->lookahead == '/') {
        while (!lexer->eof(lexer) && lexer->lookahead != '\n') skip(lexer);
      } else if (lexer->lookahead == '*') {
        skip(lexer);
        // A block comment is whitespace even where it runs over several
        // lines: the statement it sits in is not ended by them.
        unsigned star = 0;
        while (!lexer->eof(lexer)) {
          if (lexer->lookahead == '*') { star = 1; skip(lexer); continue; }
          if (star && lexer->lookahead == '/') { skip(lexer); break; }
          star = 0;
          skip(lexer);
        }
      } else {
        // not a comment, and '/' is not an operator NGPL has
        return ended;
      }
    } else {
      return ended;
    }
  }
}

bool tree_sitter_ngpl_external_scanner_scan(void *payload, TSLexer *lexer,
                                            const bool *valid_symbols) {
  Scanner *scanner = (Scanner *)payload;

  if (valid_symbols[ERROR_SENTINEL]) return false;

  // The blocks the line just reached opens or closes, one per call.
  // Nothing is read here: the whitespace that measured the indentation
  // was read when the newline before it was.
  if (scanner->pending >= 0) {
    uint16_t top = scanner->indents[scanner->depth - 1];
    if (scanner->pending > top && valid_symbols[INDENT] &&
        scanner->depth < MAX_DEPTH) {
      scanner->indents[scanner->depth++] = (uint16_t)scanner->pending;
      scanner->pending = -1;
      lexer->result_symbol = INDENT;
      return true;
    }
    if (scanner->pending < top && valid_symbols[DEDENT] && scanner->depth > 1) {
      scanner->depth--;
      if (scanner->pending >= scanner->indents[scanner->depth - 1]) {
        scanner->pending = -1;
      }
      lexer->result_symbol = DEDENT;
      return true;
    }
    scanner->pending = -1;
  }

  // The whitespace is read here rather than left to the extras,
  // because a scanner that declines is not asked again once they have
  // been skipped: what follows them has to be recognised in this call
  // or not at all.
  uint16_t indent = 0;
  bool ended = skip_gaps(lexer, &indent);

  if (lexer->eof(lexer)) {
    // what is still open is closed at the end of the file, after the
    // one newline that ends its last statement
    if (!scanner->eof_newline && valid_symbols[NEWLINE]) {
      scanner->eof_newline = true;
      lexer->result_symbol = NEWLINE;
      return true;
    }
    if (scanner->depth > 1 && valid_symbols[DEDENT]) {
      scanner->depth--;
      lexer->result_symbol = DEDENT;
      return true;
    }
    return false;
  }

  if (ended && valid_symbols[NEWLINE]) {
    scanner->pending = indent;
    lexer->result_symbol = NEWLINE;
    return true;
  }

  // A line break that ends no statement -- one inside brackets, or one
  // after an operator still waiting for its right-hand side -- is
  // whitespace, and so is the indentation of the line it began.
  if (valid_symbols[STRING] && lexer->lookahead == '"') {
    return scan_string(lexer);
  }

  return false;
}

unsigned tree_sitter_ngpl_external_scanner_serialize(void *payload, char *buffer) {
  Scanner *scanner = (Scanner *)payload;
  unsigned n = 0;
  buffer[n++] = (char)scanner->depth;
  buffer[n++] = (char)((scanner->pending < 0 ? 0 : 1) | (scanner->eof_newline ? 2 : 0));
  buffer[n++] = (char)(scanner->pending < 0 ? 0 : scanner->pending & 0xff);
  buffer[n++] = (char)(scanner->pending < 0 ? 0 : (scanner->pending >> 8) & 0xff);
  for (unsigned i = 0; i < scanner->depth && n + 2 <= TREE_SITTER_SERIALIZATION_BUFFER_SIZE; i++) {
    buffer[n++] = (char)(scanner->indents[i] & 0xff);
    buffer[n++] = (char)((scanner->indents[i] >> 8) & 0xff);
  }
  return n;
}

void tree_sitter_ngpl_external_scanner_deserialize(void *payload, const char *buffer,
                                                   unsigned length) {
  Scanner *scanner = (Scanner *)payload;
  scanner->depth = 1;
  scanner->indents[0] = 0;
  scanner->pending = -1;
  scanner->eof_newline = false;
  if (length == 0) return;
  unsigned n = 0;
  uint8_t depth = (uint8_t)buffer[n++];
  uint8_t flags = (uint8_t)buffer[n++];
  bool has_pending = (flags & 1) != 0;
  scanner->eof_newline = (flags & 2) != 0;
  uint16_t lo = (uint8_t)buffer[n++];
  uint16_t hi = (uint8_t)buffer[n++];
  scanner->pending = has_pending ? (int32_t)(lo | (hi << 8)) : -1;
  scanner->depth = 0;
  for (unsigned i = 0; i < depth && n + 2 <= length; i++) {
    uint16_t v = (uint8_t)buffer[n++];
    v |= (uint16_t)((uint8_t)buffer[n++]) << 8;
    scanner->indents[scanner->depth++] = v;
  }
  if (scanner->depth == 0) {
    scanner->depth = 1;
    scanner->indents[0] = 0;
  }
}

void *tree_sitter_ngpl_external_scanner_create(void) {
  Scanner *scanner = (Scanner *)calloc(1, sizeof(Scanner));
  scanner->depth = 1;
  scanner->indents[0] = 0;
  scanner->pending = -1;
  return scanner;
}

void tree_sitter_ngpl_external_scanner_destroy(void *payload) { free(payload); }
