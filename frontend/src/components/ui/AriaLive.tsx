import { useAppStore } from '../../stores/appStore'

/** Polite status and assertive alert regions. Mounted once in Layout. */
export default function AriaLive() {
  const statusMessage = useAppStore((s) => s.statusMessage)
  const alertMessage = useAppStore((s) => s.alertMessage)

  return (
    <>
      <div className="ag-sr-only" role="status" aria-live="polite" aria-atomic="true">
        {statusMessage}
      </div>
      <div className="ag-sr-only" role="alert" aria-live="assertive" aria-atomic="true">
        {alertMessage}
      </div>
    </>
  )
}
