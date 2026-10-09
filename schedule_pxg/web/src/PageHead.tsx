/** Заголовок экрана: название раздела (как в меню) и одна строка о том, зачем он нужен. */
export default function PageHead({ title, lede }: { title: string; lede: string }) {
  return (
    <header className="page-head">
      <h1>{title}</h1>
      <p className="lede">{lede}</p>
    </header>
  )
}
