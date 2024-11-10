frappe.ui.form.on('CN Device Log', {
    refresh: function(frm) {
        // Create chart
        create_chart(frm);
        
        frm.remove_custom_button(frappe.utils.icon("reply", "sm"));
        frm.add_custom_button(frappe.utils.icon("reply", "sm"), function() {
            window.location.href = '/app/pibiconnect?tab=LiveData';
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
      if (!r.message || !Array.isArray(r.message)) {
        // Clear existing charts if no data
        $('#main_chart').empty();
        $('#second_chart').empty();
        return;
      }

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

      let chartCreated = false;

      // Main Chart
      if (sensors.length > 0 && sensors[0].readings && sensors[0].readings.length > 0) {
        const mainSensor = sensors[0];
        const validReadings = mainSensor.readings.filter(r => r !== undefined && r !== null);
        
        if (validReadings.length > 0) {  // Only create chart if there are valid readings
          chartCreated = true;
          const average = Number((validReadings.reduce((a, b) => a + b, 0) / validReadings.length).toFixed(2));
          
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
                  dash: [2, 4]
                }
              }
            ]
          };

          const maxValue = Math.max(...validReadings, average) * 1.1;

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
                max: maxValue || 100
              },
              xAxisLabelRotation: 90
            },
            lineOptions: {
              hideDots: 1,
              regionFill: 0
            },
            tooltipOptions: {
              formatTooltipY: d => (d !== undefined && d !== null) ? d.toFixed(2) + ' ' + mainSensor.uom : 'N/A'
            }
          });
        }
      }

      // Second Chart
      if (sensors.length > 1 && sensors[1].readings && sensors[1].readings.length > 0) {
        const secondSensor1 = sensors[1];
        const secondSensor2 = sensors.length > 2 ? sensors[2] : null;
        const labels = secondSensor1.labels;

        const validReadings1 = secondSensor1.readings.filter(r => r !== undefined && r !== null);
        
        if (validReadings1.length > 0) {  // Only create chart if there are valid readings
          chartCreated = true;
          const avg1 = Number((validReadings1.reduce((a, b) => a + b, 0) / validReadings1.length).toFixed(2));
          
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
                dash: [2, 4]
              }
            }
          ];

          let avg2;
          let validReadings2 = [];
          if (secondSensor2 && secondSensor2.readings && 
              JSON.stringify(labels) === JSON.stringify(secondSensor2.labels)) {
            validReadings2 = secondSensor2.readings.filter(r => r !== undefined && r !== null);
            if (validReadings2.length > 0) {
              avg2 = Number((validReadings2.reduce((a, b) => a + b, 0) / validReadings2.length).toFixed(2));
              
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
                  dash: [2, 4]
                }
              });
            }
          }

          const allValues = [...validReadings1, ...validReadings2];
          const maxValue = Math.max(...allValues, avg1, avg2 || 0) * 1.1;

          const second_data = {
            labels: labels,
            datasets: datasets
          };

          new frappe.Chart("#second_chart", {
            title: sensors.length > 2 && validReadings2.length > 0 ?
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
                max: maxValue || 100
              },
              xAxisLabelRotation: 90
            },
            lineOptions: {
              hideDots: 1,
              regionFill: 0
            },
            tooltipOptions: {
              formatTooltipY: d => (d !== undefined && d !== null) ? d.toFixed(2) + ' ' + secondSensor1.uom : 'N/A'
            }
          });
        }
      }

      // Add button only if at least one chart was created
      if (chartCreated) {
        // Clear existing buttons first
        frm.remove_custom_button(frappe.utils.icon("image", "sm"));
        
        // Add the button
        frm.add_custom_button(frappe.utils.icon("image", "sm"), function() {
            const mainChart = document.querySelector("#main_chart svg");
            const secondChart = document.querySelector("#second_chart svg");
            
            if (mainChart) create_pic1(frm);
            if (secondChart) create_pic2(frm);
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
  
  // Merge settings
  for (let key in settings) { _settings[key] = settings[key]; }

  return new Promise(function(resolve, reject) {
    let svgNode;

    // Handle string or node input
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

    // Convert SVG to base64
    let svgXml = new XMLSerializer().serializeToString(svgNode);
    let svgBase64 = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svgXml)));

    const image = new Image();
    
    image.onload = function() {
      let finalWidth, finalHeight;

      // Calculate dimensions
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

      // Set canvas size
      canvas.width = finalWidth;
      canvas.height = finalHeight;

      // Draw and convert
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