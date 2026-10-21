export default function Placeholder({ title, note }) {
  return (
    <>
      <h1 className="page-title">{title}</h1>
      <p className="page-sub">{note}</p>
    </>
  )
}
