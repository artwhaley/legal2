import QtQuick 2.15
import QtQuick.Controls 2.15

Rectangle {
    color: "#f8f3e8"

    ListView {
        id: listView
        anchors.fill: parent
        anchors.margins: 8
        clip: true
        spacing: 0
        model: transcriptModel

        delegate: Item {
            id: rowRoot
            required property int index
            required property string entryKind
            required property int slotIndex
            required property string contextStartBoundary
            required property string contextEndBoundary
            required property string relevantStartBoundary
            required property string relevantEndBoundary
            required property string senderDisplay
            required property string body
            required property string friendlyDate
            required property string friendlyTime
            required property string attachmentSummary
            required property bool highlighted
            required property bool isCoreHit

            width: listView.width
            implicitHeight: entryKind === "separator"
                ? separatorRow.implicitHeight
                : messageRow.implicitHeight

            SeparatorRow {
                id: separatorRow
                anchors.fill: parent
                visible: entryKind === "separator"
                visualIndex: rowRoot.index
                contextStartBoundary: rowRoot.contextStartBoundary
                contextEndBoundary: rowRoot.contextEndBoundary
                relevantStartBoundary: rowRoot.relevantStartBoundary
                relevantEndBoundary: rowRoot.relevantEndBoundary
            }

            MessageRow {
                id: messageRow
                anchors.fill: parent
                visible: entryKind === "message"
                visualIndex: rowRoot.index
                highlighted: rowRoot.highlighted
                isCoreHit: rowRoot.isCoreHit
                senderDisplay: rowRoot.senderDisplay
                body: rowRoot.body
                friendlyDate: rowRoot.friendlyDate
                friendlyTime: rowRoot.friendlyTime
                attachmentSummary: rowRoot.attachmentSummary
            }
        }
    }

    component SeparatorRow: Item {
        property int visualIndex: 0
        property string contextStartBoundary: ""
        property string contextEndBoundary: ""
        property string relevantStartBoundary: ""
        property string relevantEndBoundary: ""

        implicitHeight: 26

        Rectangle {
            x: 22
            y: parent.height / 2
            width: parent.width - 44
            height: 1
            color: "#d8cebd"
        }

        Repeater {
            model: [
                { name: "context_start", strength: contextStartBoundary, color: "#0b6dd8", offset: 0 },
                { name: "relevant_start", strength: relevantStartBoundary, color: "#222222", offset: 5 },
                { name: "relevant_end", strength: relevantEndBoundary, color: "#222222", offset: 10 },
                { name: "context_end", strength: contextEndBoundary, color: "#0b6dd8", offset: 15 }
            ]
            delegate: Item {
                visible: modelData.strength.length > 0
                property int handleY: 6 + modelData.offset
                Canvas {
                    x: 22
                    y: handleY
                    width: 14
                    height: 14
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.reset()
                        ctx.globalAlpha = modelData.strength === "active" ? 1.0 : 0.35
                        ctx.fillStyle = modelData.color
                        ctx.beginPath()
                        ctx.moveTo(0, 0)
                        ctx.lineTo(width, height / 2)
                        ctx.lineTo(0, height)
                        ctx.closePath()
                        ctx.fill()
                    }
                }
                Rectangle {
                    x: 44
                    y: handleY + 6
                    width: parent.parent.width - 66
                    height: modelData.strength === "active" ? 2 : 1
                    color: modelData.color
                    opacity: modelData.strength === "active" ? 1.0 : 0.35
                }
            }
        }

        MouseArea {
            anchors.fill: parent
            enabled: true
            property string dragBoundary: ""

            function boundaryAt(x, y) {
                const handles = [
                    { name: "context_start", x: 22, y: 6, w: 14, h: 14, strength: contextStartBoundary },
                    { name: "relevant_start", x: 22, y: 11, w: 14, h: 14, strength: relevantStartBoundary },
                    { name: "relevant_end", x: 22, y: 16, w: 14, h: 14, strength: relevantEndBoundary },
                    { name: "context_end", x: 22, y: 21, w: 14, h: 14, strength: contextEndBoundary }
                ]
                for (let i = 0; i < handles.length; i++) {
                    const handle = handles[i]
                    if (handle.strength.length > 0
                            && x >= handle.x && x <= handle.x + handle.w
                            && y >= handle.y && y <= handle.y + handle.h) {
                        return handle.name
                    }
                }
                return ""
            }

            onPressed: {
                dragBoundary = boundaryAt(mouse.x, mouse.y)
                if (dragBoundary.length > 0) {
                    transcriptModel.move_boundary_to_visual_row(dragBoundary, visualIndex)
                    mouse.accepted = true
                }
            }
            onPositionChanged: {
                if (!dragBoundary.length)
                    return
                const point = mapToItem(listView.contentItem, mouse.x, mouse.y)
                const targetIndex = listView.indexAt(point.x, point.y)
                if (targetIndex >= 0)
                    transcriptModel.move_boundary_to_visual_row(dragBoundary, targetIndex)
            }
            onReleased: dragBoundary = ""
        }
    }

    component MessageRow: Item {
        property int visualIndex: 0
        property bool highlighted: false
        property bool isCoreHit: false
        property string senderDisplay: ""
        property string body: ""
        property string friendlyDate: ""
        property string friendlyTime: ""
        property string attachmentSummary: ""

        implicitHeight: Math.max(84, bodyText.contentHeight + (attachmentText.visible ? attachmentText.contentHeight : 0) + 60)

        Rectangle {
            anchors.fill: parent
            color: highlighted ? "#fff5bf" : "#f8f3e8"
        }

        Rectangle {
            visible: isCoreHit
            x: parent.width - 66
            y: 19
            width: 16
            height: 16
            radius: 8
            color: "#0b6dd8"
        }

        Rectangle {
            x: parent.width - 40
            y: 18
            width: 18
            height: 18
            radius: 9
            color: highlighted ? "#d09400" : "transparent"
            border.color: highlighted ? "#d09400" : "#9a9a9a"
            border.width: 2

            MouseArea {
                anchors.fill: parent
                onClicked: transcriptModel.toggle_highlight_row(visualIndex)
            }
        }

        Text {
            id: senderText
            x: 22
            y: 16
            width: 140
            text: senderDisplay + ":"
            font.bold: true
            color: "#222222"
        }

        Text {
            id: bodyText
            x: 174
            y: 16
            width: parent.width - 232
            wrapMode: Text.WordWrap
            color: "#222222"
            text: body
        }

        Text {
            id: metaText
            x: 174
            y: bodyText.y + Math.max(senderText.contentHeight, bodyText.contentHeight) + 10
            color: "#666666"
            text: friendlyDate + "       -   " + friendlyTime
        }

        Text {
            id: attachmentText
            visible: attachmentSummary.length > 0
            x: 174
            y: metaText.y + 18
            color: "#666666"
            text: "Attachment: " + attachmentSummary
        }
    }
}
