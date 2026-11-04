// 画面下の保存の帯に出す、エラーがあることの短い知らせ。
// エラーの本文は画面上部(または項目の横)に出すため、表の下の方で保存しても気づけるよう帯にも出す
export function savebarHint(error: string | null, hasFieldErrors = false): string | null {
  if (error) return "エラーがあります(画面の上に表示しています)";
  if (hasFieldErrors) return "入力に誤りがあります(項目の横に表示しています)";
  return null;
}
