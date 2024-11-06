frappe.ui.form.on('CN Device Log', {
  refresh: function(frm) {
    create_chart(frm);
    frm.add_custom_button(frappe.utils.icon("image","sm"), function() {
      create_pic1(frm);
      create_pic2(frm);
    });
  }
});

frappe.ui.form.on('CN Device Log', {
  refresh: function(frm) {
    create_chart(frm);
    frm.add_custom_button(frappe.utils.icon("image","sm"), function() {
      create_pic1(frm);
      create_pic2(frm);
    });
  }
});

function create_chart(frm) {
  frappe.call({
    method: "pibiconnect.pibiconnect.custom.get_chart",
    args: {
      'doc': frm.doc.name
    },
    callback: function(r) {
      if (!r.message || !Array.isArray(r.message)) return;

      const sensors = r.message;

      // Ensure chart containers exist and are empty
      if (!document.getElementById('main_chart')) {
        $('<div>').attr('id', 'main_chart').appendTo(frm.fields_dict.tablero.wrapper);
      } else {
        $('#main_chart').empty();
      }

      if (!document.getElementById('second_chart')) {
        $('<div>').attr('id', 'second_chart').appendTo(frm.fields_dict.tablero.wrapper);
      } else {
        $('#second_chart').empty();
      }

      // Main Chart
      if (sensors.length > 0) {
        const mainSensor = sensors[0];
        const average = Number((mainSensor.readings.reduce((a, b) => a + b, 0) / mainSensor.readings.length).toFixed(2));
        
        const main_data = {
          labels: mainSensor.labels,
          datasets: [
            { 
              name: mainSensor.var,
              values: mainSensor.readings,
              chartType: 'line'
            },
            {
              name: `Average ${mainSensor.var} (${average.toFixed(2)} ${mainSensor.uom})`,
              values: Array(mainSensor.labels.length).fill(average),
              chartType: 'line',
              lineOptions: { 
                dash: [2, 4]  // Changed to smaller values for dotted appearance
              }
            }
          ]
        };

        const maxValue = Math.max(...mainSensor.readings, average) * 1.1;

        new frappe.Chart("#main_chart", {
          title: `${mainSensor.var} [${mainSensor.uom}]`,
          data: main_data,
          type: 'line',
          height: 300,
          colors: ['#4682b4', '#c0c0c0'],
          valuesOverPoints: 0,
          axisOptions: {
            yAxisMode: 'span',
            xAxisMode: 'tick',
            xIsSeries: true,
            yAxis: {
              min: 0,
              max: maxValue
            },
            xAxisLabelRotation: 90
          },
          lineOptions: {
            hideDots: 1,
            regionFill: 0
          },
          tooltipOptions: {
            formatTooltipY: d => d.toFixed(2) + ' ' + mainSensor.uom
          }
        });
      }

      // Second Chart
      if (sensors.length > 1) {
        const secondSensor1 = sensors[1];
        const secondSensor2 = sensors.length > 2 ? sensors[2] : null;
        const labels = secondSensor1.labels;

        const avg1 = Number((secondSensor1.readings.reduce((a, b) => a + b, 0) / secondSensor1.readings.length).toFixed(2));
        
        const datasets = [
          {
            name: secondSensor1.var,
            values: secondSensor1.readings,
            chartType: 'line'
          },
          {
            name: `Average ${secondSensor1.var} (${avg1.toFixed(2)} ${secondSensor1.uom})`,
            values: Array(labels.length).fill(avg1),
            chartType: 'line',
            lineOptions: { 
              dash: [2, 4]  // Changed to smaller values for dotted appearance
            }
          }
        ];

        let avg2;
        if (secondSensor2 && JSON.stringify(labels) === JSON.stringify(secondSensor2.labels)) {
          avg2 = Number((secondSensor2.readings.reduce((a, b) => a + b, 0) / secondSensor2.readings.length).toFixed(2));
          
          datasets.push({
            name: secondSensor2.var,
            values: secondSensor2.readings,
            chartType: 'line'
          });

          datasets.push({
            name: `Average ${secondSensor2.var} (${avg2.toFixed(2)} ${secondSensor2.uom})`,
            values: Array(labels.length).fill(avg2),
            chartType: 'line',
            lineOptions: { 
              dash: [2, 4]  // Changed to smaller values for dotted appearance
            }
          });
        }

        const allValues = secondSensor1.readings.concat(secondSensor2 ? secondSensor2.readings : []);
        const maxValue = Math.max(...allValues, avg1, avg2 || 0) * 1.1;

        const second_data = {
          labels: labels,
          datasets: datasets
        };

        new frappe.Chart("#second_chart", {
          title: sensors.length > 2 ?
            `${secondSensor1.var} [${secondSensor1.uom}] & ${secondSensor2.var} [${secondSensor2.uom}]` :
            `${secondSensor1.var} [${secondSensor1.uom}]`,
          data: second_data,
          type: 'line',
          height: 300,
          colors: ['#4682b4', '#c0c0c0', '#28a745', '#a0a0a0'],
          valuesOverPoints: 0,
          axisOptions: {
            yAxisMode: 'span',
            xAxisMode: 'tick',
            xIsSeries: true,
            yAxis: {
              min: 0,
              max: maxValue
            },
            xAxisLabelRotation: 90
          },
          lineOptions: {
            hideDots: 1,
            regionFill: 0
          },
          tooltipOptions: {
            formatTooltipY: d => d.toFixed(2) + ' ' + secondSensor1.uom
          }
        });
      }
    }
  });
}

function create_pic1(frm) {
  setTimeout(() => {
    SVGToImage({
      svg: document.querySelector("#main_chart svg"),
      mimetype: "image/png",
      width: "auto",
      quality: 1,
      outputFormat: "base64"
    }).then(function(outputData) {
      frm.set_value('main_pic', outputData);
      refresh_field('main_pic');
    }).catch(function(err) {
      console.log(err);
      frappe.msgprint({
        title: __('Error'),
        indicator: 'red',
        message: __('Failed to convert main chart to image: ') + err.message
      });
    }); 
  }, 1000);
}

function create_pic2(frm) {
  setTimeout(() => {
    SVGToImage({
      svg: document.querySelector("#second_chart svg"),
      mimetype: "image/png",
      width: "auto",
      quality: 1,
      outputFormat: "base64"
    }).then(function(outputData) {
      frm.set_value('second_pic', outputData);
      refresh_field('second_pic');
    }).catch(function(err) {
      console.log(err);
      frappe.msgprint({
        title: __('Error'),
        indicator: 'red',
        message: __('Failed to convert second chart to image: ') + err.message
      });
    }); 
  }, 1000);
}

/**
 * Converts SVG to Image
 * @param {Object} settings Configuration settings
 * @returns {Promise}
 */
function SVGToImage(settings) {
  let _settings = {
    svg: null,
    mimetype: "image/png",
    quality: 0.92,
    width: "auto",
    height: "auto",
    outputFormat: "base64"
  };
  for (let key in settings) { _settings[key] = settings[key]; }

  return new Promise(function(resolve, reject) {
    let svgNode;

    if (typeof(_settings.svg) == "string") {
      let SVGContainer = document.createElement("div");
      SVGContainer.style.display = "none";
      SVGContainer.innerHTML = _settings.svg;
      svgNode = SVGContainer.firstElementChild;
    } else {
      svgNode = _settings.svg;
    }

    let canvas = document.createElement('canvas');
    let context = canvas.getContext('2d'); 

    let svgXml = new XMLSerializer().serializeToString(svgNode);
    let svgBase64 = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svgXml)));

    const image = new Image();
    image.onload = function() {
      let finalWidth, finalHeight;

      if (_settings.width === "auto" && _settings.height !== "auto") {
        finalWidth = (this.width / this.height) * _settings.height;
      } else if (_settings.width === "auto") {
        finalWidth = this.naturalWidth;
      } else {
        finalWidth = _settings.width;
      }

      if (_settings.height === "auto" && _settings.width !== "auto") {
        finalHeight = (this.height / this.width) * _settings.width;
      } else if (_settings.height === "auto") {
        finalHeight = this.naturalHeight;
      } else {
        finalHeight = _settings.height;
      }

      canvas.width = finalWidth;
      canvas.height = finalHeight;

      context.drawImage(this, 0, 0, finalWidth, finalHeight);
      if (_settings.outputFormat === "blob") {
        canvas.toBlob(function(blob) {
          resolve(blob);
        }, _settings.mimetype, _settings.quality);
      } else {
        resolve(canvas.toDataURL(_settings.mimetype, _settings.quality));
      }
    };

    image.onerror = function(err) {
      reject(err);
    };
    image.src = svgBase64;
  });
}